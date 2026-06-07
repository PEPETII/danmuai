"""Desktop pet subsystem: Qt window, PetDex assets, command queue, prompt injection."""

from app.pet.pet_assets import PetAssetPack, load_pet_assets
from app.pet.pet_command_service import PetCommand, PetCommandService
from app.pet.pet_prompt import build_pet_command_user_pt

__all__ = [
    "PetAssetPack",
    "PetCommand",
    "PetCommandService",
    "build_pet_command_user_pt",
    "load_pet_assets",
]
