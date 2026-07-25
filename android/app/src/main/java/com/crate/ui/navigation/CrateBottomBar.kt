package com.crate.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.crate.ui.theme.CrateTheme

/** Suite navigation shell (Spotter precedent): hairline over a flat panel bar,
 * copper for the selected tab, filled/outlined icon pairs. */
@Composable
fun CrateBottomBar(
    currentRoute: String?,
    onNavigate: (TopLevelDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = CrateTheme.colors
    Column(modifier) {
        HorizontalDivider(thickness = 1.dp, color = colors.hairline)
        NavigationBar(containerColor = colors.panel, tonalElevation = 0.dp) {
            TopLevelDestination.entries.forEach { dest ->
                val selected = currentRoute == dest.route
                NavigationBarItem(
                    selected = selected,
                    onClick = { onNavigate(dest) },
                    icon = {
                        Icon(
                            if (selected) dest.icon else dest.iconOutlined,
                            contentDescription = dest.label,
                        )
                    },
                    label = { Text(dest.label, style = MaterialTheme.typography.labelMedium) },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = colors.copper.base,
                        selectedTextColor = colors.copper.base,
                        indicatorColor = colors.copper.dim,
                        unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    ),
                )
            }
        }
    }
}
