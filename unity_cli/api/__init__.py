"""Unity CLI API Classes.

Re-exports all API classes for convenient imports:
    from unity_cli.api import ConsoleAPI, EditorAPI, ...
"""

from unity_cli.api.asset import AssetAPI
from unity_cli.api.component import ComponentAPI
from unity_cli.api.console import ConsoleAPI
from unity_cli.api.editor import EditorAPI
from unity_cli.api.gameobject import GameObjectAPI
from unity_cli.api.material import MaterialAPI
from unity_cli.api.menu import MenuAPI
from unity_cli.api.scene import SceneAPI
from unity_cli.api.screenshot import ScreenshotAPI
from unity_cli.api.selection import SelectionAPI
from unity_cli.api.tests import TestAPI
from unity_cli.api.uitree import UITreeAPI

__all__ = [
    "AssetAPI",
    "ComponentAPI",
    "ConsoleAPI",
    "EditorAPI",
    "GameObjectAPI",
    "MaterialAPI",
    "MenuAPI",
    "SceneAPI",
    "ScreenshotAPI",
    "SelectionAPI",
    "TestAPI",
    "UITreeAPI",
]
