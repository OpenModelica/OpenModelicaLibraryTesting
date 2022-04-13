# Test Results of Open-Source Modelica Libraries using OpenModelica

## Test reports

- **Overview with library test results across OMC versions**: These reports shows how libraries with full or partial support level
  (see [here](https://github.com/OpenModelica/OMPackageManager/blob/master/README.md#library-support-levels-in-openmodelica) for more details)
  are handled by released versions of OpenModelica and by the development version on the master branch. Regressions are marked in orange,
  improvements in green.
  - [Default settings](https://libraries.openmodelica.org/branches/overview.html): simulation with C runtime and default settings
  - [daeMode](https://libraries.openmodelica.org/branches/overview-dae.html): simulation with daeMode (compiler flag [--daeMode](https://openmodelica.org/doc/OpenModelicaUsersGuide/latest/omchelptext.html#omcflag-daemode))
  - [C++](https://libraries.openmodelica.org/branches/overview-c++.html): simulation with C++ runtime
  - [FMI](https://libraries.openmodelica.org/branches/overview-fmi.html): simulation with FMI and C runtime
  - [FMI C++](https://libraries.openmodelica.org/branches/overview-c++.html): simulation with FMI and C++ runtime
- **Regression reports and history plots**: regression reports are periodically generated, using the latest development version of OMC.
  Changes w.r.t. the previous report are shown. For each tested library, .svg plots are also provided, showing the trends of the
  results of each step over time.
  - [Default settings](https://libraries.openmodelica.org/branches/history/master/): default omc settings, C runtime
  - [daeMode](https://libraries.openmodelica.org/branches/history/daemode/): simulation with --daeMode
  - [C++](https://libraries.openmodelica.org/branches/history/cpp/): simulation with C++ runtime
  - [FMI](https://libraries.openmodelica.org/branches/history/master-fmi/): simulation with FMI, C runtime

## How to read the test reports

The library testsuite job is run every night on the OSMC servers, testing open-source Modelica libraries covered by the
[Package Manager](https://github.com/OpenModelica/OMPackageManager#readme) with various versions of OpenModelica,
including the development version on the master branch. The simulations are run with the C-runtime, unless specified differently.

Within each library, all models with an experiment(StopTime) annotations are run. For each tested model, the results of the following steps are reported:
- _parsing_
- _frontend_: flattening the model
- _backend_: structural analysis, index reduction, causalization, tearing, and all kind of symbolic manipulations and optimization to solve the model efficiently
- _simcode_: intermediate stap towards simulation code generation
- _templates_: generation of the actual C code
- _compilation_: compilation of the C code into a simulation executable
- _simulation_: the simulation is actually run to produce simulation results
- _verification_: if reference results file are available, they are compared with the simulation results

Clicking on the model name shows the log of phases from parsing to compilation. Clicking on the (sim) link shows the log of the runtime simulation.

## How to get your open-source library in the testsuite

If you are actively developing an open-source Modelica library using a GIT repository, you can easily get it included in the OpenModelica library testsuite. Please open a request on the [OpenModelica issue tracker](https://github.com/OpenModelica/OpenModelica/issues/new/choose).
Ideally, you should have two tests for it: one testing the latest official release, which can be used to check if changes to OMC cause regressions to the existing library, another one testing the development version, which also checks regressions caused by changes to the library code. You can then bookmark the page with the regression reports and the page with the test results obtained with your favourite settings.
