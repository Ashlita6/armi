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

r"""
Plugins allow various built-in or external functionality to be brought into the ARMI ecosystem.

This module defines the hooks that may be defined within plugins. Plugins are ultimately
incorporated into a :py:class:`armi.pluginManager.ArmiPluginManager`, which live inside
of a :py:class:`armi.apps.App` object.

The ``ArmiPluginManager`` is derived from the ``PluginManager`` class provided by the
``pluggy`` package, which provides a registry of known plugins. Rather than create one
directly, we use the :py:func:`armi.plugins.getNewPluginManager()` function, which
handles some of the setup for us.

From a high-altitude perspective, the plugins provide numerous "hooks", which allow for
ARMI to be extended in various ways. Some of these extensions are subtle and play a part
in how certain ARMI components are initialized or defined. As such, it is necessary to
register most plugins before some parts of ARMI are imported or exercised in a
meaningful way. These requirements are in flux, and will ultimately constitute part of
the specification of the ARMI plugin architecture. For now, to be safe, plugins should
be registered as soon as possible.

After forming the ``PluginManager``, the plugin hooks can be accessed through the
``hook`` attribute. E.g.::

    >>> armi.getPluginManagerOrFail().hook.exposeInterfaces(cs=cs)

Don't forget to use the keyword argument form for all arguments to hooks; ``pluggy``
requires them to enforce hook specifications.

The :py:class:`armi.apps.App` class serves as the primary storage location of the
PluginManager, and also provides some methods to get data out of the plugins more
ergonomically than through the hooks themselves.

Some things you may want to bring in via a plugin includes:

- :py:mod:`armi.settings` and their validators
- :py:mod:`armi.reactor.components` for custom geometry
- :py:mod:`armi.reactor.flags` for custom reactor components
- :py:mod:`armi.interfaces` to define new calculation sequences and interactions with
  new codes
- :py:mod:`armi.reactor.parameters` to represent new physical state on the reactor
- :py:mod:`armi.materials` for custom materials
- Elements of the :py:mod:`armi.gui`
- :py:mod:`armi.operators` for adding new operations on reactor models
- :py:mod:`armi.cli` for adding new operations on input files

Warning
-------
The plugin system was developed to support improved collaboration.  It is new and should
be considered under development. The API is subject to change as the version of the ARMI
framework approaches 1.0.

Notes
-----
Due to the nature of some of these components, there are a couple of restrictions on
the order in which things can be imported (lest we endeavor to redesign them
considerably). Examples:

  - Parameters: All parameter definitions must be present before any ``ArmiObject``
    objects are instantiated. This is mostly by choice, but also makes the most sense,
    because the ``ParameterCollection`` s are instance attributes of an ``ArmiObject``,
    which in turn use ``Parameter`` objects as *class* attributes. We should know
    what class attributes we have before making instances.

  - Blueprints: Since blueprints should be extendable with new sections, we must also
    be able to provide new *class* attributes to extend their behavior. This is
    because blueprints use the yamlize package, which uses class attributes to define
    much of the class's behavior through metaclassing. Therefore, we need to be able
    to import all plugins *before* importing blueprints.

Plugins are currently stateless. They do not have ``__init__()`` methods, and when they are
registered with the PluginMagager, the PluginManager gets the Plugin's class object
rather than an instance of that class. Also notice that all of the hooks are
``@staticmethod``\ s. As a result, they can be called directly off of the class object,
and only have access to the state passed into them to perform their function. This is a
deliberate design choice to keep the plugin system simple and to preclude a large class
of potential bugs. At some point it may make sense to revisit this.

Other customization points
--------------------------
While the Plugin API is the main place for ARMI framework customization, there are
several other areas where ARMI may be extended or customized. These typically pre-dated
the Plugin-based architecture, and as the need arise may be migrated to here.

 - Component types: Component types are registered dynamically through some metaclass
   magic, found in :py:class:`armi.reactor.components.component.ComponentType` and
   :py:class:`armi.reactor.composites.CompositeModelType`. Simply defining a new
   Component subclass should register it with the appropriate ARMI systems. While this
   is convenient, it does lead to potential issues, as the behavior of ARMI becomes
   sensitive to module import order and the like; the containing module needs to be
   imported before the registration occurs, which can be surprising.

 - Interface input files: Interfaces used to be discovered dynamically, rather than
   explicitly as they are now in the :py:meth:`armi.plugins.ArmiPlugin.exposeInterfaces`
   plugin hook. Essentially they functioned as ersatz plugins. One of the ways that they
   would customize ARMI behavior is through the
   :py:meth:`armi.physics.interface.Interface.specifyInputs` static method, which is
   still used to determine inter-Case dependencies and support cloning and hashing Case
   inputs. Going forward, this approach will likely be deprecated in favor of a plugin
   hook.

 - Fuel handler logic: The
   :py:class:`armi.physics.fuelCycle.fuelHandlers.FuelHandlerInterface` supports
   customization through the dynamic loading of fuel handler logic modules, based on
   user settings. This also predated the plugin infrastructure, and may one day be
   replaced with plugin-based fuel handler logic.
"""
from typing import Callable, Dict, List, Union, TYPE_CHECKING

import pluggy

from armi import pluginManager
from armi.utils import flags

# Not used during runtime so we could have a coverage drop here. Add the
# pragma line to tell coverage.py to skip this
# https://coverage.readthedocs.io/en/stable/excluding.html
if TYPE_CHECKING:  # pragma: no cover
    from armi.reactor.composites import Composite


HOOKSPEC = pluggy.HookspecMarker("armi")
HOOKIMPL = pluggy.HookimplMarker("armi")


class ArmiPlugin:
    """
    An ArmiPlugin provides a namespace to collect hook implementations provided by a
    single "plugin". This API is incomplete, unstable, and expected to change.

    .. impl:: Plugins have interfaces to add code to the application.
        :id: I_ARMI_PLUGIN
        :implements: R_ARMI_PLUGIN
    """

    @staticmethod
    @HOOKSPEC
    def exposeInterfaces(cs) -> List:
        """
        Function for exposing interface(s) to other code.

        .. impl:: Plugins have interfaces to the operator.
            :id: I_ARMI_PLUGIN_INTERFACES
            :implements: R_ARMI_PLUGIN_INTERFACES

        Returns
        -------
        list
            Tuples containing:

            - The insertion order to use when building an interface stack,
            - an implementation of the Interface class
            - a dictionary of kwargs to pass to an Operator when adding an instance of
              the interface class

            If no Interfaces should be active given the passed case settings, this should
            return an empty list.
        """

    @staticmethod
    @HOOKSPEC
    def defineParameters() -> Dict:
        """
        Define additional parameters for the reactor data model.

        .. impl:: Plugins can add parameters to the reactor data model.
            :id: I_ARMI_PLUGIN_PARAMS
            :implements: R_ARMI_PLUGIN_PARAMS

        .. impl:: Define an arbitrary physical parameter.
            :id: I_ARMI_PARAM
            :implements: R_ARMI_PARAM

        Returns
        -------
        dict
            Keys should be subclasses of ArmiObject, values being a
            ParameterDefinitionCollection should be added to the key's perameter
            definitions.

        Example
        -------
        >>> pluginBlockParams = parameters.ParameterDefinitionCollection()
        >>> with pluginBlockParams.createBuilder() as pb:
        ...     pb.defParam("plugBlkP1", ...)
        ...     # ...
        ...
        >>> pluginAssemParams = parameters.ParameterDefinitionCollection()
        >>> with pluginAssemParams.createBuilder() as pb:
        ...     pb.defParam("plugAsmP1", ...)
        ...     # ...
        ...
        >>> return {
        ...     blocks.Block: pluginBlockParams,
        ...     assemblies.Assembly: pluginAssemParams
        ... }
        """

    @staticmethod
    @HOOKSPEC
    def afterConstructionOfAssemblies(assemblies, cs) -> None:
        """
        Function to call after a set of assemblies are constructed.

        This hook can be used to:

        - Verify that all assemblies satisfy constraints imposed by active interfaces
          and plugins
        - Apply modifications to Assemblies based on modeling options and active
          interfaces

        Implementers may alter the state of the passed Assembly objects.

        Returns
        -------
        None
        """

    @staticmethod
    @HOOKSPEC
    def onProcessCoreLoading(core, cs, dbLoad) -> None:
        """
        Function to call whenever a Core object is newly built.

        This is usually used to set initial parameter values from inputs, either after
        constructing a Core from Blueprints, or after loading it from a database.
        """

    @staticmethod
    @HOOKSPEC
    def defineFlags() -> Dict[str, Union[int, flags.auto]]:
        """
        Function to provide new Flags definitions.

        This allows a plugin to provide novel values for the Flags system.
        Implementations should return a dictionary mapping flag names to their desired
        numerical values. In most cases, no specific value is needed, in which case
        :py:class:`armi.utils.flags.auto` should be used.

        Flags should be added to the ARMI system with great care; flag values for each
        object are stored in a bitfield, so each additional flag increases the width of
        the data needed to store them. Also, due to the `what things are` interpretation
        of flags (see :py:mod:`armi.reactor.flags`), new flags should probably refer to
        novel design elements, rather than novel behaviors.

        .. impl:: Plugins can define new, unique flags to the system.
            :id: I_ARMI_FLAG_EXTEND1
            :implements: R_ARMI_FLAG_EXTEND

        See Also
        --------
        armi.reactor.flags

        Example
        -------
        >>> def defineFlags():
        ...     return {
        ...         "FANCY": armi.utils.flags.auto()
        ...     }
        """

    @staticmethod
    @HOOKSPEC
    def defineBlockTypes() -> List:
        """
        Function for providing novel Block types from a plugin.

        This should return a list of tuples containing ``(compType, blockType)``, where
        ``blockType`` is a new ``Block`` subclass to register, and ``compType`` is the
        corresponding ``Component`` type that should activate it. For instance a
        ``HexBlock`` would be created when the largest component is a ``Hexagon``::

        Returns
        -------
        list
            [(Hexagon, HexBlock)]
        """

    @staticmethod
    @HOOKSPEC
    def defineAssemblyTypes() -> List:
        """
        Function for providing novel Assembly types from a plugin.

        This should return a list of tuples containing ``(blockType, assemType)``, where
        ``assemType`` is a new ``Assembly`` subclass to register, and ``blockType`` is
        the corresponding ``Block`` subclass that, if present in the assembly, should
        trigger it to be of the corresponding ``assemType``.

        .. warning::

            The utility of subclassing Assembly is suspect, and may soon cease to be
            supported. In practice, Assembly subclasses provide very little
            functionality beyond that on the base class, and even that functionality can
            probably be better suited elsewhere. Moving this code around would let us
            eliminate the specialized Assembly subclasses altogether. In such a case,
            this API will be removed from the framework.

        Example
        -------
        [
            (HexBlock, HexAssembly),
            (CartesianBlock, CartesianAssembly),
            (ThRZBlock, ThRZAssembly),
        ]

        Returns
        -------
        list
            List of new Block&Assembly types
        """

    @staticmethod
    @HOOKSPEC
    def defineBlueprintsSections() -> List:
        """
        Return new sections for the blueprints input method.

        This hook allows plugins to extend the blueprints functionality with their own
        sections.

        Returns
        -------
        list
            (name, section, resolutionMethod) tuples, where:

             - name : The name of the attribute to add to the Blueprints class; this
               should be a valid Python identifier.

             - section : An instance of ``yaml.Attribute`` defining the data that is
               described by the Blueprints section.

             - resolutionMethod : A callable that takes a Blueprints object and case
               settings as arguments. This will be called like an unbound instance
               method on the passed Blueprints object to initialize the state of the new
               Blueprints section.

        Notes
        -----
        Most of the sections that a plugin would want to add may be better served as
        settings, rather than blueprints sections. These sections were added to the
        blueprints mainly because the schema is more flexible, allowing namespaces and
        hierarchical collections of settings. Perhaps in the near future it would make
        sense to enhance the settings system to support these features, moving the
        blueprints extensions out into settings. This is discussed in more detail in
        T1671.
        """

    @staticmethod
    @HOOKSPEC
    def defineEntryPoints() -> List:
        """
        Return new entry points for the ARMI CLI.

        This hook allows plugins to provide their own ARMI entry points, which each
        serve as a command in the command-line interface.

        Returns
        -------
        list
            class objects which derive from the base EntryPoint class.
        """

    @staticmethod
    @HOOKSPEC
    def defineSettings() -> List:
        """
        Define configuration settings for this plugin.

        This hook allows plugins to provide their own configuration settings, which can
        participate in the :py:class:`armi.settings.caseSettings.CaseSettings`. Plugins
        may provide entirely new settings to what are already provided by ARMI, as well
        as new options or default values for existing settings. For instance, the
        framework provides a ``neutronicsKernel`` setting for selecting which global
        physics solver to use. Since we wish to enforce that the user specify a valid
        kernel, the settings validator will check to make sure that the user's requested
        kernel is among the available options. If a plugin were to provide a new
        neutronics kernel (let's say MCNP), it should also define a new option to tell
        the settings system that ``"MCNP"`` is a valid option.

        .. impl:: Plugins can add settings to the run.
            :id: I_ARMI_PLUGIN_SETTINGS
            :implements: R_ARMI_PLUGIN_SETTINGS

        Returns
        -------
        list
            A list of Settings, Options, or Defaults to be registered.

        See Also
        --------
        armi.physics.neutronics.NeutronicsPlugin.defineSettings
        armi.settings.setting.Setting
        armi.settings.setting.Option
        armi.settings.setting.Default
        """
        return []

    @staticmethod
    @HOOKSPEC
    def defineSettingsValidators(inspector) -> List:
        """
        Define the high-level settings input validators by adding them to an inspector.

        Parameters
        ----------
        inspector : :py:class:`armi.operators.settingsValidation.Inspector` instance
            The inspector to add queries to. See note below, this is not ideal.

        Notes
        -----
        These are higher-level than the input-level SCHEMA defined
        in :py:meth:`defineSettings` and are intended to be used for more
        complex cross-plugin info.

        We'd prefer to not manipulate objects passed in directly, but
        rather have the inspection happen in a measureable hook. This
        would help find misbehaving plugins.

        See Also
        --------
        armi.operators.settingsValidation.Inspector : Runs the queries

        Returns
        -------
        list
            Query objects to attach
        """
        return []

    @staticmethod
    @HOOKSPEC
    def defineCaseDependencies(case, suite):
        r"""
        Function for defining case dependencies.

        Some Cases depend on the results of other ``Case``\ s in the same ``CaseSuite``.
        Which dependencies exist, and how they are discovered depends entirely on the
        type of analysis and active interfaces, etc. This function allows a plugin to
        inspect settings and declare dependencies between the passed ``case`` and any
        other cases in the passed ``suite``.

        Parameters
        ----------
        case : Case
            The specific case for which we want to find dependencies.
        suite : CaseSuite
            A CaseSuite object to which the Case and other potential dependencies belong.

        Returns
        -------
        dependencies : set of Cases
            This should return a set containing ``Case`` objects that are considered
            dependencies of the passed ``case``. They should be members of the passed
            ``suite``.
        """

    @staticmethod
    @HOOKSPEC
    def defineGuiWidgets() -> List:
        """
        Define which settings should go in the GUI.

        Rather than making widgets here, this simply returns metadata
        as a nested dictionary saying which tab to put which settings on,
        and a little bit about how to group them.

        Returns
        -------
        widgetData : list of dict
            Each dict is nested. First level contains the tab name (e.g. 'Global Flux').
            Second level contains a box name. Third level contains help and a
            list of setting names

        See Also
        --------
        armi.gui.submitter.layout.abstractTab.AbstractTab.addSectionsFromPlugin : uses data structure

        Example
        -------
        >>> widgets = {
        ...     'Global Flux': {
        ...         'MCNP Solver Settings': {
        ...             'help': "Help message"
        ...             'settings': [
        ...                 "mcnpAddTallies",
        ...                 "useSrctp",
        ...             ]
        ...         }
        ...     }
        ... }
        """

    @staticmethod
    @HOOKSPEC
    def getOperatorClassFromRunType(runType: str):
        """Return an Operator subclass if the runType is recognized by this plugin."""

    @staticmethod
    @HOOKSPEC
    def defineParameterRenames() -> Dict:
        """
        Return a mapping from old parameter names to new parameter names.

        Occasionally, it may become necessary to alter the name of an existing
        parameter. This can lead to frustration when attempting to load from old
        database files that use the previous name. This hook allows a plugin to define
        mappings from the old name to the new name, allowing the old database to be read
        in and translated to the new parameter name.

        The following rules are followed when applying these renames:

        * When state is loaded from a database, if the parameter name in the database
          file is found in the rename dictionary, it will be mapped to that renamed
          parameter.
        * If the renamed parameter is found in the renames, then it will be mapped again
          to new parameter name. This process is repeated until there are no more
          renames left. This allows for parameters to be renamed multiple times, and for
          a database from several generations prior to still be readable, so long as the
          history of renames is intact.
        * If at the end of the above process, the parameter name is not a defined
          parameter for the appropriate ``ArmiObject`` type, an exception is raised.
        * If any of the ``renames`` keys match any currently-defined parameters, an
          exception is raised.
        * If any of the ``renames`` collide with another plugin's ``renames``, an
          exception is raised.

        Returns
        -------
        renames : dict
            Keys should be an old parameter name, where the corresponding values are
            the new parameter name.

        Example
        -------
        The following would allow databases with values for either ``superOldParam`` or
        ``oldParam`` to be read into ``currentParam``::

            return {"superOldParam": "oldParam",
                    "oldParam": "currentParam"}
        """

    @staticmethod
    @HOOKSPEC
    def mpiActionRequiresReset(cmd) -> bool:
        """
        Flag indicating when a reactor reset is required.

        Commands are sent through operators either as strings (old) or as MpiActions (newer).
        After some are sent, the reactor must be reset. This hook says when to reset. The
        reset operation is a (arguably suboptimal) response to some memory issues in
        very large and long-running cases.

        Parameters
        ----------
        cmd :  str or MpiAction
            The ARMI mpi command being sent

        Returns
        -------
        bool

        See Also
        --------
        armi.operators.operatorMPI.OperatorMPI.workerOperate : Handles these flags
        """

    @staticmethod
    @HOOKSPEC
    def getReportContents(r, cs, report, stage, blueprint) -> None:
        """
        To generate a report.

        For more information, see :doc:`/developer/reports`.

        Parameters
        ----------
        r : Reactor

        cs : Settings

        report : ReportContent
            Report object to add contents to

        stage : ReportStage
            begin/standard/or end (stage of the report for when inserting BOL vs. EOL
            content)

        blueprint : Blueprint, optional
            for a reactor (if None, only partial contents created)
        """

    @staticmethod
    @HOOKSPEC
    def defineSystemBuilders() -> Dict[str, Callable[[str], "Composite"]]:
        """
        Convert a user-string from the systems section into a valid composite builder.

        Parameters
        ----------
        name : str
            Name of the system type defined by the user, e.g., ``"core"``

        Returns
        -------
        dict
            Dictionary that maps a grid type from the input file (e.g., ``"core"``)
            to a function responsible for building a grid of that type, e.g.,

            .. code::

                {
                    "core": armi.reactor.reactors.Core,
                    "sfp": armi.reactor.assemblyLists.SpentFuelPool,
                }

        Notes
        -----
        The default :class:`~armi.reactor.ReactorPlugin` defines a ``"core"`` lookup
        and a ``"sfp"`` lookup, triggered to run after all other hooks have been run.
        """


class UserPlugin(ArmiPlugin):
    """
    A variation on the ArmiPlugin meant to be created at runtime, from the ``userPlugins`` setting.

    This is obviously a more limited use-case than the usual ArmiPlugin, as those are meant
    to be defined at import time, instead of run time. As such, this class has some built-in
    tooling to limit how these run-time plugins are used. They are meant to be more limited.

    Notes
    -----
    The usual ArmiPlugin is much more flexible, if the UserPlugin does not support what
    you want to do, just use an ArmiPlugin.
    """

    def __init__(self, *args, **kwargs):
        ArmiPlugin.__init__(self, *args, **kwargs)
        self.__enforceLimitations()

    def __enforceLimitations(self):
        """
        This method enforces that UserPlugins are more limited than regular ArmiPlugins.

        UserPlugins are different from regular plugins in that they can be defined during
        a run, and as such, we want to limit how flexible they are, so we can correctly
        corral their side effects during a run.
        """
        if issubclass(self.__class__, UserPlugin):
            assert (
                len(self.__class__.defineParameters()) == 0
            ), "UserPlugins cannot define parameters, consider using an ArmiPlugin."
            assert (
                len(self.__class__.defineParameterRenames()) == 0
            ), "UserPlugins cannot define parameter renames, consider using an ArmiPlugin."
            assert (
                len(self.__class__.defineSettings()) == 0
            ), "UserPlugins cannot define new Settings, consider using an ArmiPlugin."
            # NOTE: These are the class methods that we are staunchly _not_ allowing people
            # to change in this class. If you need these, please use a regular ArmiPlugin.
            self.defineParameterRenames = lambda: {}
            self.defineSettings = lambda: []
            self.defineSettingsValidators = lambda: []

    @staticmethod
    @HOOKSPEC
    def defineParameters():
        """
        Prevents defining additional parameters.

        .. warning:: This is not overridable.

        Notes
        -----
        It is a designed limitation of user plugins that they not define parameters.
        Parameters are defined when the App() is read in, which is LONG before the settings
        file has been read. So the parameters are defined before we discover the user plugin.
        If this is a feature you need, just use an ArmiPlugin.
        """
        return {}

    @staticmethod
    @HOOKSPEC
    def defineParameterRenames():
        """
        Prevents parameter renames.

        .. warning:: This is not overridable.

        Notes
        -----
        It is a designed limitation of user plugins that they not generate parameter renames,
        Parameters are defined when the App() is read in, which is LONG before the settings
        file has been read. So the parameters are defined before we discover the user plugin.
        If this is a feature you need, just use a normal Plugin.
        """
        return {}

    @staticmethod
    @HOOKSPEC
    def defineSettings():
        """
        Prevents new settings.

        .. warning:: This is not overridable.

        Notes
        -----
        It is a designed limitation of user plugins that they not define new settings,
        so that they are able to be added to the plugin stack during run time.
        """
        return []

    @staticmethod
    @HOOKSPEC
    def defineSettingsValidators(inspector):
        """
        Prevents new settings validators.

        .. warning:: This is not overridable.

        Notes
        -----
        It is a designed limitation of user plugins that they not define new settings,
        so that they are able to be added to the plugin stack during run time.
        """
        return []


def getNewPluginManager() -> pluginManager.ArmiPluginManager:
    """Return a new plugin manager with all of the hookspecs pre-registered."""
    pm = pluginManager.ArmiPluginManager("armi")
    pm.add_hookspecs(ArmiPlugin)
    return pm


def collectInterfaceDescriptions(mod, cs):
    """
    Adapt old-style ``describeInterfaces`` to the new plugin interface.

    Old describeInterfaces implementations would return an interface class and kwargs
    for adding to an operator. Now we expect an ORDER as well. This takes a module and
    case settings and staples the module's ORDER attribute to the tuple and checks to
    make sure that a None is replaced by an empty list.
    """
    from armi import interfaces

    val = mod.describeInterfaces(cs)

    if val is None:
        return []
    if isinstance(val, list):
        return [
            interfaces.InterfaceInfo(mod.ORDER, klass, kwargs) for klass, kwargs in val
        ]

    klass, kwargs = val
    return [interfaces.InterfaceInfo(mod.ORDER, klass, kwargs)]


class PluginError(RuntimeError):
    """
    Special exception class for use when a plugin appears to be non-conformant.

    These should always come from some form of programmer error, and indicates
    conditions such as:

     - A plugin improperly implementing a hook, when possible to detect.
     - A collision between components provided by plugins (e.g. two plugins providing
       the same Blueprints section)
    """
