"""Unity project version detection and info parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unity_cli.exceptions import ProjectError, ProjectVersionError


@dataclass(frozen=True)
class ProjectVersion:
    """Unity project version info."""

    version: str
    revision: str | None = None

    @classmethod
    def from_file(cls, project_path: Path) -> ProjectVersion:
        """Parse ProjectSettings/ProjectVersion.txt.

        Args:
            project_path: Path to the Unity project root directory.

        Returns:
            ProjectVersion with version and optional revision.

        Raises:
            ProjectVersionError: If file not found or invalid format.
        """
        version_file = project_path / "ProjectSettings/ProjectVersion.txt"

        if not version_file.exists():
            raise ProjectVersionError(
                f"ProjectVersion.txt not found: {version_file}",
                code="PROJECT_VERSION_NOT_FOUND",
            )

        content = version_file.read_text(encoding="utf-8")

        # Parse m_EditorVersion: 2022.3.10f1
        version_match = re.search(r"m_EditorVersion:\s*(.+)", content)
        if not version_match:
            raise ProjectVersionError(
                "Invalid ProjectVersion.txt format: m_EditorVersion not found",
                code="PROJECT_VERSION_INVALID",
            )

        version = version_match.group(1).strip()

        # Parse optional revision: m_EditorVersionWithRevision: 2022.3.10f1 (abc123)
        revision: str | None = None
        revision_match = re.search(r"m_EditorVersionWithRevision:\s*.+\(([^)]+)\)", content)
        if revision_match:
            revision = revision_match.group(1).strip()

        return cls(version=version, revision=revision)


def parse_project_version(project_path: Path) -> ProjectVersion:
    """Parse ProjectVersion.txt from a Unity project.

    Convenience function that wraps ProjectVersion.from_file().
    """
    return ProjectVersion.from_file(project_path)


def is_unity_project(path: Path) -> bool:
    """Check if path is a valid Unity project.

    A valid Unity project contains:
    - Assets/ directory
    - ProjectSettings/ directory
    - ProjectSettings/ProjectVersion.txt file
    """
    if not path.is_dir():
        return False

    assets_dir = path / "Assets"
    project_settings_dir = path / "ProjectSettings"
    version_file = project_settings_dir / "ProjectVersion.txt"

    return (
        assets_dir.exists()
        and assets_dir.is_dir()
        and project_settings_dir.exists()
        and project_settings_dir.is_dir()
        and version_file.exists()
    )


# =============================================================================
# Project Settings Parsing
# =============================================================================


@dataclass(frozen=True)
class ProjectSettings:
    """Unity project settings from ProjectSettings.asset."""

    product_name: str
    company_name: str
    version: str  # bundleVersion (application version)
    default_screen_width: int
    default_screen_height: int

    @classmethod
    def from_file(cls, project_path: Path) -> ProjectSettings:
        """Parse ProjectSettings/ProjectSettings.asset (YAML)."""
        settings_file = project_path / "ProjectSettings/ProjectSettings.asset"

        if not settings_file.exists():
            raise ProjectError(
                f"ProjectSettings.asset not found: {settings_file}",
                code="PROJECT_SETTINGS_NOT_FOUND",
            )

        content = settings_file.read_text(encoding="utf-8")

        def extract_value(key: str, default: str = "") -> str:
            match = re.search(rf"{key}:\s*(.+)", content)
            return match.group(1).strip() if match else default

        def extract_int(key: str, default: int = 0) -> int:
            match = re.search(rf"{key}:\s*(\d+)", content)
            return int(match.group(1)) if match else default

        return cls(
            product_name=extract_value("productName", "Unknown"),
            company_name=extract_value("companyName", "Unknown"),
            version=extract_value("bundleVersion", "0.1"),
            default_screen_width=extract_int("defaultScreenWidth", 1024),
            default_screen_height=extract_int("defaultScreenHeight", 768),
        )


@dataclass(frozen=True)
class BuildScene:
    """Scene included in build."""

    path: str
    enabled: bool


@dataclass(frozen=True)
class BuildSettings:
    """Unity build settings from EditorBuildSettings.asset."""

    scenes: list[BuildScene] = field(default_factory=list)

    @classmethod
    def from_file(cls, project_path: Path) -> BuildSettings:
        """Parse ProjectSettings/EditorBuildSettings.asset (YAML)."""
        build_file = project_path / "ProjectSettings/EditorBuildSettings.asset"

        if not build_file.exists():
            return cls(scenes=[])

        content = build_file.read_text(encoding="utf-8")
        scenes: list[BuildScene] = []

        # Parse scenes using regex (simple YAML parsing)
        scene_blocks = re.findall(r"-\s+enabled:\s*(\d+)\s+path:\s*([^\s]+)", content)
        for enabled_str, path in scene_blocks:
            scenes.append(BuildScene(path=path, enabled=enabled_str == "1"))

        return cls(scenes=scenes)


@dataclass(frozen=True)
class PackageInfo:
    """Package dependency info."""

    name: str
    version: str
    is_local: bool = False


@dataclass(frozen=True)
class PackageManifest:
    """Unity package manifest from Packages/manifest.json."""

    dependencies: list[PackageInfo] = field(default_factory=list)

    @classmethod
    def from_file(cls, project_path: Path) -> PackageManifest:
        """Parse Packages/manifest.json."""
        manifest_file = project_path / "Packages/manifest.json"

        if not manifest_file.exists():
            return cls(dependencies=[])

        content = manifest_file.read_text(encoding="utf-8")
        data = json.loads(content)
        deps = data.get("dependencies", {})

        packages: list[PackageInfo] = []
        for name, version in deps.items():
            # Skip built-in modules
            if name.startswith("com.unity.modules."):
                continue
            is_local = version.startswith("file:")
            packages.append(PackageInfo(name=name, version=version, is_local=is_local))

        # Sort by name
        packages.sort(key=lambda p: p.name)
        return cls(dependencies=packages)


@dataclass
class ProjectInfo:
    """Complete Unity project information."""

    path: Path
    unity_version: ProjectVersion
    settings: ProjectSettings
    build_settings: BuildSettings
    packages: PackageManifest

    @classmethod
    def from_path(cls, project_path: Path) -> ProjectInfo:
        """Gather all project information from files."""
        project_path = project_path.resolve()

        if not is_unity_project(project_path):
            raise ProjectError(
                f"Not a valid Unity project: {project_path}",
                code="INVALID_PROJECT",
            )

        return cls(
            path=project_path,
            unity_version=ProjectVersion.from_file(project_path),
            settings=ProjectSettings.from_file(project_path),
            build_settings=BuildSettings.from_file(project_path),
            packages=PackageManifest.from_file(project_path),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "path": str(self.path),
            "unity_version": self.unity_version.version,
            "unity_revision": self.unity_version.revision,
            "product_name": self.settings.product_name,
            "company_name": self.settings.company_name,
            "version": self.settings.version,
            "screen_size": {
                "width": self.settings.default_screen_width,
                "height": self.settings.default_screen_height,
            },
            "build_scenes": [{"path": s.path, "enabled": s.enabled} for s in self.build_settings.scenes],
            "packages": [
                {"name": p.name, "version": p.version, "local": p.is_local} for p in self.packages.dependencies
            ],
        }


# =============================================================================
# Tag/Layer Settings Parsing
# =============================================================================


@dataclass(frozen=True)
class TagLayerSettings:
    """Unity tag and layer settings from TagManager.asset."""

    tags: list[str] = field(default_factory=list)
    layers: list[tuple[int, str]] = field(default_factory=list)  # (index, name)
    sorting_layers: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, project_path: Path) -> TagLayerSettings:
        """Parse ProjectSettings/TagManager.asset."""
        tag_file = project_path / "ProjectSettings/TagManager.asset"

        if not tag_file.exists():
            return cls()

        content = tag_file.read_text(encoding="utf-8")

        # Parse tags
        tags: list[str] = []
        tags_match = re.search(r"tags:\s*\n((?:\s+-\s*.+\n)*)", content)
        if tags_match:
            for tag in re.findall(r"-\s*(.+)", tags_match.group(1)):
                tag = tag.strip()
                if tag:
                    tags.append(tag)

        # Parse layers (32 slots, many empty)
        layers: list[tuple[int, str]] = []
        layers_match = re.search(r"layers:\s*\n((?:\s+-.*\n)*)", content)
        if layers_match:
            # Each line is "  - LayerName" or "  - " (empty)
            layer_lines = layers_match.group(1).strip().split("\n")
            for i, line in enumerate(layer_lines):
                # Remove "  - " prefix
                layer = line.strip().lstrip("-").strip()
                if layer:
                    layers.append((i, layer))

        # Parse sorting layers
        sorting_layers: list[str] = []
        sorting_match = re.search(r"m_SortingLayers:\s*\n((?:\s+-.*\n)*)", content)
        if sorting_match:
            for name in re.findall(r"name:\s*(.+)", sorting_match.group(1)):
                sorting_layers.append(name.strip())

        return cls(tags=tags, layers=layers, sorting_layers=sorting_layers)


# =============================================================================
# Quality Settings Parsing
# =============================================================================


@dataclass(frozen=True)
class QualityLevel:
    """Single quality level settings."""

    name: str
    shadow_resolution: int
    shadow_distance: float
    vsync_count: int
    lod_bias: float
    anti_aliasing: int


@dataclass(frozen=True)
class QualitySettings:
    """Unity quality settings from QualitySettings.asset."""

    current_quality: int
    levels: list[QualityLevel] = field(default_factory=list)

    @classmethod
    def from_file(cls, project_path: Path) -> QualitySettings:
        """Parse ProjectSettings/QualitySettings.asset."""
        quality_file = project_path / "ProjectSettings/QualitySettings.asset"

        if not quality_file.exists():
            return cls(current_quality=0)

        content = quality_file.read_text(encoding="utf-8")

        # Current quality level
        current_match = re.search(r"m_CurrentQuality:\s*(\d+)", content)
        current_quality = int(current_match.group(1)) if current_match else 0

        # Parse quality levels
        levels: list[QualityLevel] = []

        # Split by "- serializedVersion:" to get each level
        level_blocks = re.split(r"(?=\s+-\s+serializedVersion:)", content)

        def get_int(text: str, key: str, default: int = 0) -> int:
            m = re.search(rf"{key}:\s*(\d+)", text)
            return int(m.group(1)) if m else default

        def get_float(text: str, key: str, default: float = 0.0) -> float:
            m = re.search(rf"{key}:\s*([\d.]+)", text)
            return float(m.group(1)) if m else default

        for block in level_blocks[1:]:  # Skip first (header)
            name_match = re.search(r"name:\s*(.+)", block)
            if not name_match:
                continue

            name = name_match.group(1).strip()

            levels.append(
                QualityLevel(
                    name=name,
                    shadow_resolution=get_int(block, "shadowResolution"),
                    shadow_distance=get_float(block, "shadowDistance"),
                    vsync_count=get_int(block, "vSyncCount"),
                    lod_bias=get_float(block, "lodBias"),
                    anti_aliasing=get_int(block, "antiAliasing"),
                )
            )

        return cls(current_quality=current_quality, levels=levels)


# =============================================================================
# Assembly Definition Parsing
# =============================================================================


@dataclass(frozen=True)
class AssemblyDefinition:
    """Assembly definition from .asmdef file."""

    name: str
    path: Path
    references: list[str] = field(default_factory=list)
    include_platforms: list[str] = field(default_factory=list)
    exclude_platforms: list[str] = field(default_factory=list)
    allow_unsafe: bool = False
    auto_referenced: bool = True

    @classmethod
    def from_file(cls, asmdef_path: Path) -> AssemblyDefinition:
        """Parse a single .asmdef file."""
        content = asmdef_path.read_text(encoding="utf-8")
        data = json.loads(content)

        return cls(
            name=data.get("name", asmdef_path.stem),
            path=asmdef_path,
            references=data.get("references", []),
            include_platforms=data.get("includePlatforms", []),
            exclude_platforms=data.get("excludePlatforms", []),
            allow_unsafe=data.get("allowUnsafeCode", False),
            auto_referenced=data.get("autoReferenced", True),
        )


def find_assembly_definitions(project_path: Path) -> list[AssemblyDefinition]:
    """Find all .asmdef files in Assets/ directory."""
    project_path = project_path.resolve()
    assets_dir = project_path / "Assets"

    if not assets_dir.exists():
        return []

    assemblies: list[AssemblyDefinition] = []

    for asmdef_path in assets_dir.rglob("*.asmdef"):
        try:
            asm = AssemblyDefinition.from_file(asmdef_path)
            assemblies.append(asm)
        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by name
    assemblies.sort(key=lambda a: a.name)
    return assemblies
