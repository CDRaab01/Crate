package com.crate.ui.navigation

/** Navigation routes. Grows phase by phase; keep route strings unique and stable. */
sealed class Screen(val route: String) {
    data object Gate : Screen("gate")
    data object Login : Screen("login")
    data object Home : Screen("home")
    data object Capture : Screen("capture")
    data object Review : Screen("review")
    data object Items : Screen("items")
    data object Settings : Screen("settings")
    data object Inbox : Screen("inbox")

    data object ItemDetail : Screen("items/{itemId}") {
        const val ARG = "itemId"
        fun withId(id: String) = "items/$id"
    }

    companion object {
        /** Every route, for the uniqueness guard test. */
        val all: List<Screen> =
            listOf(Gate, Login, Home, Capture, Review, Items, ItemDetail, Settings, Inbox)
    }
}
