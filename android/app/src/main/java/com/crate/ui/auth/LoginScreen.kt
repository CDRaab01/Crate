package com.crate.ui.auth

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.crate.ui.components.BrandLogo
import com.crate.ui.components.CrateWordmark
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.Caption
import design.pulse.ui.components.PulseButton

/**
 * SSO-only login (Magpie pattern): "Sign in with Dragonfly" is the whole surface — no
 * email/password fallback exists, on the client or the server.
 */
@Composable
fun LoginScreen(
    onSignedIn: () -> Unit,
    viewModel: AuthViewModel = hiltViewModel(),
) {
    val signInState by viewModel.signInState.collectAsState()

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        viewModel.completeSuiteSignIn(result.data)
    }

    LaunchedEffect(signInState) {
        if (signInState is UiState.Success) onSignedIn()
    }

    LoginContent(
        signInState = signInState,
        onSignIn = { launcher.launch(viewModel.suiteAuthorizeIntent()) },
    )
}

/** Stateless visual layer — also rendered by the Roborazzi screenshot tests. */
@Composable
internal fun LoginContent(
    signInState: UiState<Unit>,
    onSignIn: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BrandLogo(size = 96.dp)
        Spacer(Modifier.height(24.dp))
        CrateWordmark(large = true, color = MaterialTheme.colorScheme.onBackground)
        Spacer(Modifier.height(8.dp))
        Caption(text = "Photo in. Package out.")

        Spacer(Modifier.height(48.dp))

        when (val state = signInState) {
            is UiState.Loading -> CircularProgressIndicator(
                color = CrateTheme.colors.copper.base
            )
            else -> {
                PulseButton(
                    text = "Sign in with Dragonfly",
                    onClick = onSignIn,
                    gradient = CrateTheme.colors.heroGradient,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (state is UiState.Error) {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = state.message,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}
