from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from werkzeug.utils import secure_filename

from app.core.config import settings
from app.core.security import check_egress_permission, is_egress_enabled
from app.models.nist_library import NistLibrary
from app.services.rate_limiter import RateLimiter
from libs.nist_scraper.scraper import NISTScraper

if TYPE_CHECKING:
    from app.models.user import User

_RESOLUTION_PATTERN = re.compile(rb"##RESOLUTION=\s*([0-9.]+)")

_nist_limiter = RateLimiter(
    max_calls=settings.max_nist_downloads_per_hour,
    period_sec=3600,
    state_path=settings.data_dir / "rate_limits.json",
)


class NISTService:
    def __init__(self, session: AsyncSession, user: Optional["User"] = None) -> None:
        self.session = session
        self.user = user
        self.scraper = NISTScraper()

    async def _check_nist_egress(self) -> None:
        """Check if NIST queries are allowed for this user."""
        # First check global egress
        if not is_egress_enabled():
            raise HTTPException(
                status_code=403,
                detail="Network egress is disabled. Enable egress to use NIST WebBook."
            )
        # Then check user-specific permission
        if not await check_egress_permission(
            self.user,
            "allow_nist_queries",
            data_type="metadata",
            destination="nist",
            session=self.session,
        ):
            raise HTTPException(
                status_code=403,
                detail="NIST queries are disabled in your privacy settings."
            )

    async def search(self, query: str) -> list[dict[str, str]]:
        await self._check_nist_egress()
        return await self.scraper.search(query)

    async def download(
        self,
        cas_number: str,
        compound_name: Optional[str],
        resolution: Optional[str],
        index: int | None = None,
    ) -> NistLibrary:
        await self._check_nist_egress()
        if not _nist_limiter.allow():
            raise HTTPException(status_code=429, detail="NIST rate limit exceeded")

        content = await self.scraper.download_spectrum(cas_number, index=index or 0)
        if not content:
            raise HTTPException(status_code=404, detail="Spectrum not found")

        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Downloaded spectrum too large")

        extracted_resolution = self._extract_resolution(content)
        resolution_value = resolution or extracted_resolution or "unknown"
        target_path = self._build_download_path(
            cas_number, compound_name or cas_number, resolution_value
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        result = await self.session.execute(
            select(NistLibrary).where(
                NistLibrary.cas_number == cas_number,
                NistLibrary.resolution == resolution_value,
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.compound_name = compound_name or entry.compound_name
            entry.file_path = target_path.relative_to(settings.data_dir).as_posix()
        else:
            entry = NistLibrary(
                cas_number=cas_number,
                compound_name=compound_name or cas_number,
                resolution=resolution_value,
                file_path=target_path.relative_to(settings.data_dir).as_posix(),
            )
            self.session.add(entry)

        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def list_library(self, limit: int = 100, offset: int = 0) -> list[NistLibrary]:
        result = await self.session.execute(
            select(NistLibrary)
            .order_by(NistLibrary.downloaded_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    def _extract_resolution(self, content: bytes) -> Optional[str]:
        match = _RESOLUTION_PATTERN.search(content)
        return match.group(1).decode("ascii") if match else None

    def _build_download_path(
        self, cas_number: str, compound_name: str, resolution: str
    ) -> Path:
        safe_name = secure_filename(compound_name) or secure_filename(cas_number)
        safe_resolution = re.sub(r"[^0-9A-Za-z._-]", "", resolution)
        filename = f"{cas_number}_{safe_name}_{safe_resolution}cm_boxcar.jdx"
        return settings.data_dir / "nist_library" / "downloaded" / filename

    async def parse_jcamp_spectrum(self, library_id: int) -> dict:
        """Parse JCAMP-DX file to extract wavenumbers and intensities for plotting"""
        result = await self.session.execute(
            select(NistLibrary).where(NistLibrary.id == library_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Library entry not found")

        file_path = settings.data_dir / entry.file_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Spectrum file not found")

        # Parse JCAMP-DX file
        wavenumbers, intensities = self._parse_jcamp_file(file_path)

        return {
            "wavenumbers": wavenumbers,
            "intensities": intensities,
            "compound_name": entry.compound_name,
            "cas_number": entry.cas_number,
            "resolution": entry.resolution,
            "num_points": len(wavenumbers),
        }

    def _parse_jcamp_file(self, filepath: Path) -> tuple[list[float], list[float]]:
        """
        Manually parse a JCAMP-DX file to extract wavenumber and intensity data.
        Handles both standard (X,Y) format and compressed (X++(Y..Y)) format.
        Based on Original/Pull_FTIR_from_NIST/convert_plot_NIST_spectra.py
        """
        wavenumbers = []
        intensities = []
        in_data_section = False
        x_factor = 1.0
        y_factor = 1.0
        delta_x = 1.0  # Default increment for compressed format

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()

                # Extract metadata
                if line.startswith('##XFACTOR='):
                    x_factor = float(line.split('=')[1])
                elif line.startswith('##YFACTOR='):
                    y_factor = float(line.split('=')[1])
                elif line.startswith('##DELTAX='):
                    delta_x = float(line.split('=')[1])
                elif line.startswith('##XYDATA=') or line.startswith('##XYPOINTS='):
                    in_data_section = True
                    continue
                elif line.startswith('##'):
                    in_data_section = False
                    continue

                # Parse data section
                if in_data_section and line:
                    try:
                        parts = line.split()
                        if len(parts) >= 2:
                            # First value is the starting X
                            x_start = float(parts[0]) * x_factor

                            # Remaining values are Y values at incremental X positions
                            # Handle compressed format: X++(Y..Y)
                            for i, y_str in enumerate(parts[1:]):
                                x = x_start + (i * delta_x)
                                y = float(y_str) * y_factor
                                wavenumbers.append(x)
                                intensities.append(y)
                    except ValueError:
                        continue

        return wavenumbers, intensities
