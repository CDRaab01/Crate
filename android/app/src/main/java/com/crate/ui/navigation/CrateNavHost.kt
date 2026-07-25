package com.crate.ui.navigation

import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.crate.ui.auth.AuthViewModel
import com.crate.ui.auth.LoginScreen
import com.crate.ui.capture.CaptureScreen
import com.crate.ui.home.HomeScreen
import com.crate.ui.inbox.InboxScreen
import com.crate.ui.items.ItemDetailScreen
import com.crate.ui.items.ItemsScreen
import com.crate.ui.review.ReviewScreen
import com.crate.ui.settings.SettingsScreen
import com.crate.ui.ship.ShipScreen

private val bottomBarRoutes = TopLevelDestination.entries.map { it.route }.toSet()

@Composable
fun CrateNavHost(
    gateViewModel: GateViewModel = hiltViewModel(),
    authViewModel: AuthViewModel = hiltViewModel(),
) {
    val navController = rememberNavController()

    // Forced sign-out (refresh failure) → back to Login, clearing the stack.
    LaunchedEffect(Unit) {
        authViewModel.logoutEvents.collect {
            navController.navigate(Screen.Login.route) {
                popUpTo(0) { inclusive = true }
            }
        }
    }

    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    Scaffold(
        bottomBar = {
            if (currentRoute in bottomBarRoutes) {
                CrateBottomBar(
                    currentRoute = currentRoute,
                    onNavigate = { dest ->
                        navController.navigate(dest.route) {
                            popUpTo(navController.graph.findStartDestination().id) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                )
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Gate.route,
            // Without consumeWindowInsets, detail screens' inner TopAppBars re-apply the
            // same system-bar insets a second time — the suite's double-gap landmine.
            modifier = Modifier.padding(padding).consumeWindowInsets(padding),
        ) {
            composable(Screen.Gate.route) {
                // Immediate bounce: Home when a session exists, Login otherwise.
                LaunchedEffect(Unit) {
                    val target =
                        if (gateViewModel.isSignedIn()) Screen.Home.route else Screen.Login.route
                    navController.navigate(target) {
                        popUpTo(Screen.Gate.route) { inclusive = true }
                    }
                }
            }
            composable(Screen.Login.route) {
                LoginScreen(
                    onSignedIn = {
                        navController.navigate(Screen.Home.route) {
                            popUpTo(Screen.Login.route) { inclusive = true }
                        }
                    },
                )
            }
            composable(Screen.Home.route) {
                HomeScreen(
                    onSettings = { navController.navigate(Screen.Settings.route) },
                    onItem = { id -> navController.navigate(Screen.ItemDetail.withId(id)) },
                    onGoReview = { navController.navigate(Screen.Review.route) },
                    onGoInbox = { navController.navigate(Screen.Inbox.route) },
                )
            }
            composable(Screen.Capture.route) { CaptureScreen() }
            composable(Screen.Review.route) { ReviewScreen() }
            composable(Screen.Items.route) {
                ItemsScreen(onItem = { id -> navController.navigate(Screen.ItemDetail.withId(id)) })
            }
            composable(Screen.ItemDetail.route) {
                ItemDetailScreen(
                    onShip = { id -> navController.navigate(Screen.Ship.withId(id)) },
                    onBack = { navController.popBackStack() },
                )
            }
            composable(Screen.Ship.route) {
                ShipScreen(onBack = { navController.popBackStack() })
            }
            composable(Screen.Inbox.route) { InboxScreen() }
            composable(Screen.Settings.route) {
                SettingsScreen(
                    onSignedOut = {
                        navController.navigate(Screen.Login.route) { popUpTo(0) { inclusive = true } }
                    },
                    onBack = { navController.popBackStack() },
                )
            }
        }
    }
}
