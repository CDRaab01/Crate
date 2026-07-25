package com.crate

import com.crate.ui.navigation.Screen
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.Test

class ScreenRoutesTest {

    @Test
    fun `routes are unique`() {
        val routes = Screen.all.map { it.route }
        assertEquals(routes.size, routes.toSet().size, "duplicate navigation routes: $routes")
    }

    @Test
    fun `routes are stable non-blank lowercase tokens`() {
        Screen.all.forEach { screen ->
            assertTrue(screen.route.isNotBlank(), "blank route on $screen")
            assertEquals(
                screen.route,
                screen.route.lowercase(),
                "route should be lowercase: ${screen.route}",
            )
        }
    }
}
