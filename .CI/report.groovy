// The report stage of .CI/Jenkinsfile, which turns the results of the runs into
// the pages published on libraries.openmodelica.org. Loaded next to
// .CI/common.groovy and reached as `report.<function>()`.
//
// The branches a page covers are the GITBRANCHES* of the stage's environment;
// the functions here read them from `env` rather than taking them as arguments,
// so that the lists stay where the pipeline declares them.

/**
  * The three configuration files together: the standard libraries, the outdated
  * ones and the nonstandard ones. Passing them to one report.py run is what
  * makes a "combined" page.
  */
def allConfigs() {
  return 'configs/conf.json configs/conf-old.json configs/conf-nonstandard.json'
}

/**
  * Every branch a run of all-reports.py and all-plots.py covers.
  */
def allBranches() {
  return [env.GITBRANCHES,
          env.GITBRANCHES_FMI,
          env.GITBRANCHES_NEWINST,
          env.GITBRANCHES_DAE,
          env.GITBRANCHES_NEWBACKEND_DAE,
          env.GITBRANCHES_CPP,
          env.GITBRANCHES_WASM_JIT,
          // The jobs that are a table of their own rather than one of the lists above.
          'conversion',
          'heavy_tests',
          'generateSymbolicJacobian',
          'gbode',
          'cvode',
          'ida'].join(' ')
}

/**
  * The workspace the pages are built in: the ones of the previous run are
  * removed, the OpenModelica clone that all-reports.py reads the commits from is
  * updated, and the omcversion rows of runs that produced no results are dropped.
  */
def prepare() {
  sh 'rm -rf *.html history'
  sh '''
  if ! test -d OpenModelica; then
    git clone https://openmodelica.org/git-readonly/OpenModelica.git
  fi
  cd OpenModelica
  git fetch
  '''
  sh './clean-empty-omcversion-dates.py'
}

/**
  * The per-library reports and the plots of every branch.
  */
def reportsAndPlots() {
  sh "./all-reports.py --email --omcgitdir=OpenModelica ${allBranches()}"
  sh "./all-plots.py ${allBranches()}"
}

/**
  * One overview page. report.py always writes overview.html, so a page is that
  * file under the name the publisher uploads it as.
  *
  * @param name:     File name of the page, e.g. `overview-fmi.html`.
  * @param branches: The branches it holds a column for.
  * @param configs:  The configuration files it covers, the standard libraries
  *                  by default.
  */
def overview(String name, String branches, String configs = 'configs/conf.json') {
  sh "./report.py --branches='${branches}' ${configs}"
  sh "mv overview.html ${name}"
}

/**
  * The four pages a set of branches gets: the standard libraries, all three
  * configurations combined, the outdated libraries and the nonstandard ones.
  * `suffix` is what tells the four sets apart, e.g. `-fmi`.
  */
def overviewSet(String suffix, String branches) {
  overview("overview${suffix}.html", branches)
  overview("overview-combined${suffix}.html", branches, allConfigs())
  overview("overview-old-libs${suffix}.html", branches, 'configs/conf-old.json')
  overview("overview-nonstandard-libs${suffix}.html", branches, 'configs/conf-nonstandard.json')
}

/**
  * Every overview page of the report stage.
  */
def overviews() {
  def standard = "${env.GITBRANCHES} ${env.GITBRANCHES_WASM_JIT}"
  overview('overview-combined.html', standard, allConfigs())
  overview('overview-old-libs.html', standard, 'configs/conf-old.json')
  overview('overview-nonstandard-libs.html', standard, 'configs/conf-nonstandard.json')
  overview('overview-special-jobs.html', "${env.GITBRANCHES_SPECIAL} conversion")
  overview('overview-generateSymbolicJacobian.html', 'generateSymbolicJacobian')
  overview('overview-heavy_tests.html', 'heavy_tests', 'configs/heavy_tests.json')
  overview('overview-cvode.html', 'cvode master')
  overview('overview-gbode.html', 'gbode master')
  overview('overview-ida.html', 'ida master')
  // The three ways one wasm artifact is simulated, against master: they share
  // an export, so only the simulation and the verification tell them apart.
  overview('overview-wasm-jit.html', "${env.GITBRANCHES_WASM_JIT} master")
  overview('overview-c++.html', env.GITBRANCHES_CPP)

  overviewSet('-oldinst', env.GITBRANCHES_NEWINST)
  overviewSet('-fmi', env.GITBRANCHES_FMI)
  overviewSet('-dae', env.GITBRANCHES_DAE)
  overviewSet('-newbackend-dae', env.GITBRANCHES_NEWBACKEND_DAE)

  // Last, and the one page that keeps the name report.py gives it: overview.html
  // is what the site links to.
  sh "./report.py --branches='${env.GITBRANCHES}' configs/conf.json"
}

/**
  * Uploads the pages, after saying how many of them there are and which.
  */
def publish() {
  sh 'date'
  sh 'find overview*.html history -type f | wc -l'
  sh 'find overview*.html history'

  sshPublisher(publishers: [sshPublisherDesc(configName: 'LibraryTestingReports', transfers: [sshTransfer(sourceFiles: 'overview*.html,history/**')])])
}

/**
  * The report of one pull request run, which the report stage above does not
  * cover: that one compares a branch against its own previous run, which a pull
  * request has none of.
  *
  * @param pullRequest: The number of the tested pull request.
  * @param baseline:    The branch its results are compared against.
  * @param comment:     Post the summary as a comment on the pull request. Needs
  *                     the github-token credential; whoever the token belongs to
  *                     is who the comment comes from.
  */
def pullRequestReport(String pullRequest, String baseline, boolean comment) {
  sh 'rm -rf history'
  def prReport = "./pr-report.py '${pullRequest}' --baseline='${(baseline ?: 'master').trim()}'"
  if (comment) {
    withCredentials([string(credentialsId: 'github-token', variable: 'GITHUB_TOKEN')]) {
      sh "${prReport} --comment"
    }
  } else {
    sh prReport
  }
  // The summary is in the build log as well, so a run without a token still
  // leaves it somewhere to copy from.
  sh 'cat history/pr-*/00_comment.md'

  sshPublisher(publishers: [sshPublisherDesc(configName: 'LibraryTestingReports', transfers: [sshTransfer(sourceFiles: 'history/**')])])
}

return this
