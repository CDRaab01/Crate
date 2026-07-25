package com.crate.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.crate.ui.auth.AuthViewModel
import com.crate.ui.auth.LoginScreen
import com.crate.ui.home.HomeScreen

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

    NavHost(navController = navController, startDestination = Screen.Gate.route) {
        composable(Screen.Gate.route) {
            // Immediate bounce: Home when a session exists, Login otherwise.
            LaunchedEffect(Unit) {
                val target = if (gateViewModel.isSignedIn()) Screen.Home.route else Screen.Login.route
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
        composable(Screen.Home.route) { HomeScreen() }
    }
}
