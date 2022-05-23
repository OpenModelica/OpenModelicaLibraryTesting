# How to set up the library testing configuration file

The [conf.json](configs/conf.json) file specifies which versions of the libraries included in the package manager are ran, and with which options.
For each test entry, there are several fields:
- `library`: name of the library
- `libraryVersion`: version of the library; this is the content of the library version annotation for tagged versions, or the name of the branch
  as specified in one of the `branches` field of the Package Manager server [repos.json](https://github.com/OpenModelica/OMPackageManager/blob/master/repos.json) file,
  in case a non-tagged version needs to be tested. If no version is provided, the latest tagged version is tested automatically
- `libraryVersionNameForTests`: this is appended with an underscore to the name of the library in the test report name
- `ignoreModelPrefix`: skips testing all models that start with that string

There are many other fields to manage reference results, that can be either stored locally on the server, or fetched from a remote GIT repository,
and for providing extra flags and settings to OMC when running the tests. Please refer to [conf.json](configs/conf.json) for more examples, and to
the [master result directory](https://libraries.openmodelica.org/branches/master/) for an example of the corresponding output. Please
note that some files and/or directory there may be leftovers of old test runs, only consider recent ones if you want to understand what the outcome
of a certain test configuration is.

Note that in order to test a library it is also necessary to
- include it in the package manager (see the [OMPackageManager Instructions](https://github.com/OpenModelica/OMPackageManager#readme)), where it is possible to configure branches that may be tested besides the tagged released versions, e.g. the master branch or some maintenance branch
- have it installed by the CI. In order to do that, it needs to be added to the [installLibraries.mos](https://github.com/OpenModelica/OpenModelicaLibraryTesting/blob/master/.CI/installLibraries.mos) file.
