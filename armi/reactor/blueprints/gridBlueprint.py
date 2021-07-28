# Copyright 2019 TerraPower, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Input definitions for Grids.

Grids are given names which can be referred to on other input structures
(like core maps and pin maps).

These are in turn interpreted into concrete things at lower levels. For
example:

* Core map lattices get turned into :py:mod:`armi.reactor.grids`,
  which get set to ``core.spatialGrid``.
* Block pin map lattices get applied to the components to provide
  some subassembly spatial details

Lattice inputs here are floating in space. Specific dimensions
and anchor points are handled by the lower-level objects definitions. This
is intended to maximize lattice reusability.

See Also
--------
armi.utils.asciimaps
    Description of the ascii maps and their formats.

Examples
--------
::

    grids:
        control:
            geom: hex
            symmetry: full
            lattice map: |
               - - - - - - - - - 1 1 1 1 1 1 1 1 1 4
                - - - - - - - - 1 1 1 1 1 1 1 1 1 1 1
                 - - - - - - - 1 8 1 1 1 1 1 1 1 1 1 1
                  - - - - - - 1 1 1 1 1 1 1 1 1 1 1 1 1
                   - - - - - 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                    - - - - 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                     - - - 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                      - - 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                       - 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                        7 1 1 1 1 1 1 1 1 0 1 1 1 1 1 1 1 1 1
                         1 1 1 1 1 1 1 1 2 1 1 1 1 1 1 1 1 1
                          1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                           1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                            1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
                             1 1 1 1 1 1 1 1 1 1 1 1 1 1
                              1 1 1 1 1 1 1 1 1 3 1 1 1
                               1 1 1 1 1 1 1 1 1 1 1 1
                                1 6 1 1 1 1 1 1 1 1 1
                                 1 1 1 1 1 1 1 1 1 1
        sfp:
            geom: cartesian
            lattice pitch:
                x: 25.0
                y: 25.0
            lattice map: |
                2 2 2 2 2
                2 1 1 1 2
                2 1 3 1 2
                2 3 1 1 2
                2 2 2 2 2

        core:
            geom: hex
            symmetry: third periodic
            origin:
                x: 0.0
                y: 10.1
                z: 1.1
            lattice map: |
                -     SH   SH   SH
                -  SH   SH   SH   SH
                 SH   RR   RR   RR   SH
                   RR   RR   RR   RR   SH
                 RR   RR   RR   RR   RR   SH
                   RR   OC   OC   RR   RR   SH
                     OC   OC   OC   RR   RR   SH
                   OC   OC   OC   OC   RR   RR
                     OC   MC   OC   OC   RR   SH
                       MC   MC   PC   OC   RR   SH
                     MC   MC   MC   OC   OC   RR
                       MC   MC   MC   OC   RR   SH
                         PC   MC   MC   OC   RR   SH
                       MC   MC   MC   MC   OC   RR
                         IC   MC   MC   OC   RR   SH
                           IC   US   MC   OC   RR
                         IC   IC   MC   OC   RR   SH
                           IC   MC   MC   OC   RR
                         IC   IC   MC   PC   RR   SH

"""
import copy
import itertools
from typing import Sequence, Optional, Tuple

import numpy
import yamlize

from armi.localization.exceptions import InputError
from armi.utils import asciimaps
from armi.reactor import geometry
from armi.reactor import grids
from armi import runLog


class Triplet(yamlize.Object):
    """A x, y, z triplet for coordinates or lattice pitch."""

    x = yamlize.Attribute(type=float)
    y = yamlize.Attribute(type=float, default=0.0)
    z = yamlize.Attribute(type=float, default=0.0)

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class GridBlueprint(yamlize.Object):
    """
    A grid input blueprint.

    These directly build Grid objects and contain information about
    how to populate the Grid with child ArmiObjects for the Reactor Model.

    The grids get origins either from a parent block (for pin lattices)
    or from a System (for Cores, SFPs, and other components).

    Attributes
    ----------
    name : str
        The grid name
    geom : str
        The geometry of the grid (e.g. 'cartesian')
    latticeMap : str
        An asciimap representation of the lattice contents
    latticeDimensions : Triplet
        An x/y/z Triplet with grid dimensions in cm. This is used to specify a uniform
        grid, such as Cartesian or Hex. Mutually exclusive with gridBounds.
    gridBounds : dict
        A dictionary containing explicit grid boundaries. Specific keys used will depend
        on the type of grid being defined. Mutually exclusive with latticeDimensions.
    symmetry : str
        A string defining the symmetry mode of the grid
    gridContents : dict
        A {(i,j): str} dictionary mapping spatialGrid indices
        in 2-D to string specifiers of what's supposed to be in the grid.

    """

    name = yamlize.Attribute(key="name", type=str)
    geom = yamlize.Attribute(key="geom", type=str, default=geometry.HEX)
    latticeMap = yamlize.Attribute(key="lattice map", type=str, default=None)
    latticeDimensions = yamlize.Attribute(
        key="lattice pitch", type=Triplet, default=None
    )
    gridBounds = yamlize.Attribute(key="grid bounds", type=dict, default=None)
    symmetry = yamlize.Attribute(
        key="symmetry",
        type=str,
        default=str(
            geometry.SymmetryType(
                geometry.DomainType.THIRD_CORE, geometry.BoundaryType.PERIODIC
            )
        ),
    )
    # gridContents is the final form of grid contents information;
    # it is set regardless of how the input is read. This is how all
    # grid contents information is written out.
    gridContents = yamlize.Attribute(key="grid contents", type=dict, default=None)

    @gridContents.validator
    def gridContents(self, value):  # pylint: disable=method-hidden
        if value is None:
            return True
        if not all(isinstance(key, tuple) for key in value.keys()):
            raise InputError(
                "Keys need to be presented as [i, j]. Check the blueprints."
            )

    def __init__(
        self,
        name=None,
        geom=geometry.HEX,
        latticeMap=None,
        symmetry=str(
            geometry.SymmetryType(
                geometry.DomainType.THIRD_CORE, geometry.BoundaryType.PERIODIC
            )
        ),
        gridContents=None,
        gridBounds=None,
    ):
        """
        A Grid blueprint.

        Notes
        -----
        yamlize does not call an __init__ method, instead it uses __new__ and setattr
        this is only needed for when you want to make this object from a non-YAML
        source.

        .. warning:: This is a Yamlize object, so ``__init__`` never really gets called.
        Only ``__new__`` does.

        """
        self.name = name
        self.geom = str(geom)
        self.latticeMap = latticeMap
        self.symmetry = str(symmetry)
        self.gridContents = gridContents
        self.gridBounds = gridBounds

    def construct(self):
        """Build a Grid from a grid definition."""
        self._readGridContents()
        grid = self._constructSpatialGrid()
        return grid

    def _constructSpatialGrid(self):
        """
        Build spatial grid.

        If you do not enter latticeDimensions, a unit grid will be produced which must
        be adjusted to the proper dimensions (often by inspection of children) at a
        later time.
        """
        symmetry = (
            geometry.SymmetryType.fromStr(self.symmetry) if self.symmetry else None
        )
        geom = self.geom
        maxIndex = self._getMaxIndex()
        runLog.extra("Creating the spatial grid")
        if geom in (geometry.RZT, geometry.RZ):
            if self.gridBounds is None:
                # This check is regrattably late. It would be nice if we could validate
                # that bounds are provided if R-Theta mesh is being used.
                raise InputError(
                    "Grid bounds must be provided for `{}` to specify a grid with "
                    "r-theta components.".format(self.name)
                )
            for key in ("theta", "r"):
                if key not in self.gridBounds:
                    raise InputError(
                        "{} grid bounds were not provided for `{}`.".format(
                            key, self.name
                        )
                    )

            # convert to list, otherwise it is a CommentedSeq
            theta = numpy.array(self.gridBounds["theta"])
            radii = numpy.array(self.gridBounds["r"])
            for l, name in ((theta, "theta"), (radii, "radii")):
                if not _isMonotonicUnique(l):
                    raise InputError(
                        "Grid bounds for {}:{} is not sorted or contains "
                        "duplicates. Check blueprints.".format(self.name, name)
                    )
            spatialGrid = grids.ThetaRZGrid(bounds=(theta, radii, (0.0, 0.0)))
        if geom in (geometry.HEX, geometry.HEX_CORNERS_UP):
            pitch = self.latticeDimensions.x if self.latticeDimensions else 1.0
            # add 2 for potential dummy assems
            spatialGrid = grids.HexGrid.fromPitch(
                pitch,
                numRings=maxIndex + 2,
                pointedEndUp=geom == geometry.HEX_CORNERS_UP,
            )
        elif geom == geometry.CARTESIAN:
            # if full core or not cut-off, bump the first assembly from the center of
            # the mesh into the positive values.
            xw, yw = (
                (self.latticeDimensions.x, self.latticeDimensions.y)
                if self.latticeDimensions
                else (1.0, 1.0)
            )

            # Specifically in the case of grid blueprints, where we have grid contents
            # available, we can also infer "through center" based on the contents.
            # Note that the "through center" symmetry check cannot be performed when
            # the grid contents has not been provided (i.e., None or empty).
            if self.gridContents:
                nx, ny = _getGridSize(self.gridContents.keys())
                if nx == ny and nx % 2 == 1:
                    symmetry.isThroughCenterAssembly = True

            isOffset = symmetry is not None and not symmetry.isThroughCenterAssembly

            spatialGrid = grids.CartesianGrid.fromRectangle(
                xw, yw, numRings=maxIndex + 1, isOffset=isOffset
            )
        runLog.debug("Built grid: {}".format(spatialGrid))
        # set geometric metadata on spatialGrid. This information is needed in various
        # parts of the code and is best encapsulated on the grid itself rather than on
        # the container state.
        spatialGrid._geomType: str = str(self.geom)
        self.symmetry = str(symmetry)
        spatialGrid._symmetry: str = self.symmetry
        return spatialGrid

    def _getMaxIndex(self):
        """
        Find the max index in the grid contents.

        Used to limit the size of the spatialGrid. Used to be
        called maxNumRings.
        """
        if self.gridContents:
            return max(itertools.chain(*zip(*self.gridContents.keys())))
        else:
            return 6

    def expandToFull(self):
        """
        Unfold the blueprints to represent full symmetry.

        .. note:: This relatively rudimentary, and copies entries from the
            currently-represented domain to their corresponding locations in full
            symmetry.  This may not produce the desired behavior for some scenarios,
            such as when expanding fuel shuffling paths or the like. Future work may
            make this more sophisticated.
        """
        if (
            geometry.SymmetryType.fromAny(self.symmetry).domain
            == geometry.DomainType.FULL_CORE
        ):
            # No need!
            return

        grid = self.construct()

        newContents = copy.copy(self.gridContents)
        for idx, contents in self.gridContents.items():
            equivs = grid.getSymmetricEquivalents(idx)
            for idx2 in equivs:
                newContents[idx2] = contents
        self.gridContents = newContents
        split = geometry.THROUGH_CENTER_ASSEMBLY in self.symmetry
        self.symmetry = str(
            geometry.SymmetryType(
                geometry.DomainType.FULL_CORE,
                geometry.BoundaryType.NO_SYMMETRY,
                throughCenterAssembly=split,
            )
        )

    def _readGridContents(self):
        """
        Read the specifiers as a function of grid position.

        The contents can either be provided as:

        * A dict mapping indices to specifiers (default output of this)
        * An asciimap

        The output will always be stored in ``self.gridContents``.
        """
        if self.gridContents:
            return
        elif self.latticeMap:
            self._readGridContentsLattice()

        if self.gridContents is None:
            # Make sure we have at least something; clients shouldn't have to worry
            # about whether gridContents exist at all.
            self.gridContents = dict()

    def _readGridContentsLattice(self):
        """Read an ascii map of grid contents.

        This update the gridContents attribute, which is a dict mapping grid i,j,k
        indices to textual specifiers (e.g. ``IC``))
        """
        symmetry = geometry.SymmetryType.fromStr(self.symmetry)
        geom = geometry.GeomType.fromStr(self.geom)
        latticeCls = asciimaps.asciiMapFromGeomAndSym(self.geom, self.symmetry)
        asciimap = latticeCls()
        asciimap.readAscii(self.latticeMap)
        self.gridContents = dict()

        iOffset = 0
        jOffset = 0
        if (
            geom == geometry.GeomType.CARTESIAN
            and symmetry.domain == geometry.DomainType.FULL_CORE
        ):
            # asciimaps is not smart about where the center should be, so we need to
            # offset appropriately to get (0,0) in the middle
            nx, ny = _getGridSize(asciimap.keys())

            # turns out this works great for even and odd cases. love it when integer
            # math works in your favor
            iOffset = int(-nx / 2)
            jOffset = int(-ny / 2)

        for (i, j), spec in asciimap.items():
            if spec == "-":
                # skip placeholders
                continue
            self.gridContents[i + iOffset, j + jOffset] = spec

    def getLocators(self, spatialGrid: grids.Grid, latticeIDs: list):
        """
        Return spatialLocators in grid corresponding to lattice IDs.

        This requires a fully-populated ``gridContents`` attribute.
        """
        if latticeIDs is None:
            return []
        if self.gridContents is None:
            return []
        # tried using yamlize to coerce ints to strings but failed
        # after much struggle, so we just auto-convert here to deal
        # with int-like specifications.
        # (yamlize.StrList fails to coerce when ints are provided)
        latticeIDs = [str(i) for i in latticeIDs]
        locators = []
        for (i, j), spec in self.gridContents.items():
            locator = spatialGrid[i, j, 0]
            if spec in latticeIDs:
                locators.append(locator)
        return locators

    def getMultiLocator(self, spatialGrid, latticeIDs):
        """Create a MultiIndexLocation based on lattice IDs."""
        spatialLocator = grids.MultiIndexLocation(grid=spatialGrid)
        spatialLocator.extend(self.getLocators(spatialGrid, latticeIDs))
        return spatialLocator


class Grids(yamlize.KeyedList):
    item_type = GridBlueprint
    key_attr = GridBlueprint.name


def _isMonotonicUnique(l: Sequence[float]) -> bool:
    """
    Check that the provided sequence increases monotonically, and has no duplicates.
    """
    # we want to safely compare for equality. numpy/list semantics are different
    l = list(l)
    if len(set(l)) != len(l):
        # Duplicates
        return False

    # Assuming that we are going to fail anyways if this returns False, so be lazy and
    # compare to sorted list. Fast happy path.
    if sorted(l) != l:
        return False

    return True


def _getGridSize(idx) -> Tuple[int, int]:
    """
    Return the number of spaces between the min and max of a collection of (int, int)
    tuples, inclusive.

    This essentially returns the number of grid locations along the i, and j dimesions,
    given the (i,j) indices of each occupied location. This is useful for determining
    certain grid offset behavior.
    """
    nx = max(key[0] for key in idx) - min(key[0] for key in idx) + 1
    ny = max(key[1] for key in idx) - min(key[1] for key in idx) + 1

    return nx, ny
