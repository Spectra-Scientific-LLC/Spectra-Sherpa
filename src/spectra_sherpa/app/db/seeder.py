import logging
import shutil

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.experiments import add_experiment_file, create_experiment, experiment_dir

logger = logging.getLogger(__name__)


async def seed_data() -> None:
    """
    Seed the database with sample data from app/db/seeds.
    """
    seeds_dir = settings.backend_root / "app" / "db" / "seeds"
    if not seeds_dir.exists():
        logger.warning(f"Seeds directory not found: {seeds_dir}")
        return

    async with async_session() as session:
        # Get default user
        from sqlalchemy import select

        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("No user found to assign seed data to.")
            return

        # Check if seed experiment already exists
        result = await session.execute(select(Experiment).where(Experiment.name == "Sample Data"))
        if result.scalar_one_or_none():
            logger.info("Sample Data already seeded.")
            return

        # Create Experiment
        experiment = await create_experiment(
            session=session,
            user_id=user.id,
            name="Sample Data",
            description="Auto-generated sample datasets for testing.",
            metadata={},
        )

        # Copy files and register
        for file_path in seeds_dir.glob("*"):
            if file_path.name.startswith("."):  # skip .DS_Store
                continue

            # Destination in canonical data/experiments/exp_XXX/raw/
            exp_dir = experiment_dir(experiment.id)
            dest_dir = exp_dir / "raw"
            dest_dir.mkdir(parents=True, exist_ok=True)

            dest_file = dest_dir / file_path.name
            shutil.copy2(file_path, dest_file)

            # Store relative path (relative to exp_dir) for secure download checks
            rel_path = dest_file.relative_to(exp_dir)
            await add_experiment_file(
                session=session,
                experiment_id=experiment.id,
                file_path=str(rel_path),
                file_type=file_path.suffix.lstrip("."),
                stage="raw",
                file_size_bytes=dest_file.stat().st_size,
            )
            logger.info(f"Seeded file: {file_path.name}")

        await session.commit()
