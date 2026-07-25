pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Crate"
include(":app")

// PULSE design system, consumed as a composite build of the sibling Pulse repo
// (<parent>/{Crate,Pulse}); Gradle substitutes the design.pulse:pulse-ui dependency with the
// included build. Pulse is REQUIRED — the app's whole theme lives there — so there is no
// exists() gate: a missing checkout should fail loudly, and CI checks the Pulse repo out next
// to this one (see .github/workflows/ci.yml).
includeBuild("../../Pulse")
