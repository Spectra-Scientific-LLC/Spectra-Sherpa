import logging
import shutil
from pathlib import Path

from app.core.config import settings
from app.db.session import async_session
from app.models.experiment import Experiment
from app.models.user import User
from app.services.experiments import create_experiment, add_experiment_file

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
            if file_path.name.startswith("."): # skip .DS_Store
                continue
            
            # Destination in data/experiments/{id}/raw/
            dest_dir = settings.data_dir / "experiments" / str(experiment.id) / "raw"
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            dest_file = dest_dir / file_path.name
            shutil.copy2(file_path, dest_file)
            
            # Register in DB
            await add_experiment_file(
                session=session,
                experiment_id=experiment.id,
                file_path=str(dest_file),
                file_type=file_path.suffix.lstrip("."),
                stage="raw",
                file_size_bytes=dest_file.stat().st_size
            )
            logger.info(f"Seeded file: {file_path.name}")
            
        await session.commit()
