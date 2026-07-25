package com.crate.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FactCheck
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.outlined.FactCheck
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.ui.graphics.vector.ImageVector

/** The five bottom-bar tabs. Routes reuse the existing Screen entries — no new routes. */
enum class TopLevelDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
    val iconOutlined: ImageVector,
) {
    HOME(Screen.Home.route, "Home", Icons.Filled.Home, Icons.Outlined.Home),
    SELL(Screen.Capture.route, "Sell", Icons.Filled.PhotoCamera, Icons.Outlined.PhotoCamera),
    REVIEW(Screen.Review.route, "Review", Icons.Filled.FactCheck, Icons.Outlined.FactCheck),
    REGISTRY(Screen.Items.route, "Registry", Icons.Filled.Inventory2, Icons.Outlined.Inventory2),
    INBOX(Screen.Inbox.route, "Inbox", Icons.Filled.Inbox, Icons.Outlined.Inbox),
}
