package com.crate.ui.navigation

/** Navigation routes. Grows phase by phase; keep route strings unique and stable. */
sealed class Screen(val route: String) {
    data object Gate : Screen("gate")
    data object Login : Screen("login")
    data object Home : Screen("home")

    companion object {
        /** Every route, for the uniqueness guard test. */
        val all: List<Screen> = listOf(Gate, Login, Home)
    }
}
