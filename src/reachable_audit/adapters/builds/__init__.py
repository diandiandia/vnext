"""Build-system adapters."""

from .base import BuildAdapter, ParsedBuildDependency, ParsedBuildUnit
from .cargo import CargoBuildAdapter
from .bundler import BundlerBuildAdapter
from .cmake import CMakeBuildAdapter
from .composer import ComposerBuildAdapter
from .dotnet import DotnetBuildAdapter
from .go import GoBuildAdapter
from .gradle import GradleBuildAdapter
from .make import MakeBuildAdapter
from .maven import MavenBuildAdapter
from .npm import NpmBuildAdapter
from .perl import PerlBuildAdapter
from .python import PythonBuildAdapter
from .sbt import SbtBuildAdapter
from .swift import SwiftBuildAdapter


BUILD_ADAPTERS: tuple[BuildAdapter, ...] = (
    PythonBuildAdapter(),
    CMakeBuildAdapter(),
    MakeBuildAdapter(),
    CargoBuildAdapter(),
    DotnetBuildAdapter(),
    ComposerBuildAdapter(),
    BundlerBuildAdapter(),
    SbtBuildAdapter(),
    PerlBuildAdapter(),
    GoBuildAdapter(),
    NpmBuildAdapter(),
    MavenBuildAdapter(),
    GradleBuildAdapter(),
    SwiftBuildAdapter(),
)

__all__ = [
    "BUILD_ADAPTERS",
    "BundlerBuildAdapter",
    "BuildAdapter",
    "CMakeBuildAdapter",
    "ComposerBuildAdapter",
    "DotnetBuildAdapter",
    "MakeBuildAdapter",
    "ParsedBuildDependency",
    "ParsedBuildUnit",
    "PerlBuildAdapter",
    "SbtBuildAdapter",
]