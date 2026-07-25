package com.crate.screenshot

import android.app.Application
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemPhotoDto
import com.crate.data.remote.MessageDto
import com.crate.data.remote.PriceEventDto
import com.crate.data.remote.RateDto
import com.crate.data.remote.SaleDto
import com.crate.ui.auth.LoginContent
import com.crate.ui.home.HomeContent
import com.crate.ui.home.HomeStats
import com.crate.ui.inbox.MessageCard
import com.crate.ui.items.Detail
import com.crate.ui.navigation.CrateBottomBar
import com.crate.ui.navigation.Screen
import com.crate.ui.review.DraftCard
import com.crate.ui.settings.DropPolicyCard
import com.crate.ui.ship.RateRow
import com.crate.ui.ship.WeightConfirmCard
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import com.github.takahirom.roborazzi.ExperimentalRoborazziApi
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.RoborazziOptions
import com.github.takahirom.roborazzi.captureRoboImage
import design.pulse.ui.components.SectionHeader
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * JVM screenshot tests (Robolectric native graphics + Roborazzi) — render Crate screens to PNGs
 * without a device or emulator. Run with `:app:testDebugUnitTest`; images land in
 * `app/screenshots/`. Record with `-Proborazzi.test.record=true`. Mirrors the Cookbook/Plate
 * suite pattern. Photos render as empty frames here (fixtures carry no server), which keeps the
 * scenes network-free.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(application = Application::class, sdk = [34], qualifiers = RobolectricDeviceQualifiers.Pixel5)
class ScreenshotTest {

    @get:Rule val compose = createComposeRule()

    // A small tolerance so sub-pixel AA / font-hinting noise across machines doesn't flag a diff.
    private val roborazziOptions = RoborazziOptions(
        compareOptions = RoborazziOptions.CompareOptions(changeThreshold = 0.03f),
    )

    @OptIn(ExperimentalRoborazziApi::class)
    private fun capture(name: String, dark: Boolean, content: @Composable () -> Unit) {
        compose.setContent {
            CrateTheme(darkTheme = dark) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) { content() }
            }
        }
        compose.onRoot().captureRoboImage("screenshots/$name.png", roborazziOptions = roborazziOptions)
    }

    @Test fun home_light() = capture("home_light", dark = false) { HomeScene() }
    @Test fun home_dark() = capture("home_dark", dark = true) { HomeScene() }

    @Test fun settings_light() = capture("settings_light", dark = false) { SettingsScene() }
    @Test fun settings_dark() = capture("settings_dark", dark = true) { SettingsScene() }

    @Test fun shell_light() = capture("shell_light", dark = false) { ShellScene() }
    @Test fun shell_dark() = capture("shell_dark", dark = true) { ShellScene() }

    @Test fun login_light() = capture("login_light", dark = false) { LoginScene() }
    @Test fun login_dark() = capture("login_dark", dark = true) { LoginScene() }

    @Test fun review_light() = capture("review_light", dark = false) { ReviewScene() }
    @Test fun review_dark() = capture("review_dark", dark = true) { ReviewScene() }

    @Test fun item_detail_light() = capture("item_detail_light", dark = false) { DetailScene() }
    @Test fun item_detail_dark() = capture("item_detail_dark", dark = true) { DetailScene() }

    @Test fun ship_light() = capture("ship_light", dark = false) { ShipScene() }
    @Test fun ship_dark() = capture("ship_dark", dark = true) { ShipScene() }

    @Test fun inbox_light() = capture("inbox_light", dark = false) { InboxScene() }
    @Test fun inbox_dark() = capture("inbox_dark", dark = true) { InboxScene() }
}

@Composable
private fun LoginScene() {
    LoginContent(signInState = UiState.Idle, onSignIn = {})
}

@Composable
private fun HomeScene() {
    HomeContent(
        stats = HomeStats(
            active = 4,
            sold = 11,
            drafts = 2,
            recent = listOf(templatedDraft, lowConfidenceDraft, soldItem),
            unresolvedMessages = 1,
            loaded = true,
        ),
    )
}

@Composable
private fun SettingsScene() {
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        design.pulse.ui.components.ProfileHeader(
            name = "Chris",
            email = "chris@dragonflymedia.org",
            channel = CrateTheme.colors.copper.base,
            channelDim = CrateTheme.colors.copper.dim,
        )
        design.pulse.ui.components.SettingsSection(title = "Selling") {
            DropPolicyCard(
                enabled = true,
                intervalDays = 14,
                stepPercent = "10",
                preference = "cheapest",
                onSave = { _, _, _, _ -> },
            )
        }
    }
}

@Composable
private fun ShellScene() {
    Column(modifier = Modifier.fillMaxSize()) {
        androidx.compose.foundation.layout.Spacer(Modifier.weight(1f))
        CrateBottomBar(currentRoute = Screen.Home.route, onNavigate = {})
    }
}

@Composable
private fun ReviewScene() {
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Review", style = MaterialTheme.typography.headlineSmall)
        DraftCard(
            item = templatedDraft,
            onSave = { _, _ -> },
            onDismiss = {},
            onChoosePrice = {},
            onPost = {},
        )
        DraftCard(
            item = lowConfidenceDraft,
            onSave = { _, _ -> },
            onDismiss = {},
            onChoosePrice = {},
            onPost = {},
        )
    }
}

@Composable
private fun DetailScene() {
    Detail(
        item = soldItem,
        priceEvents = priceHistory,
        sale = sale,
        onShip = {},
    )
}

@Composable
private fun ShipScene() {
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Shimano Curado 200K baitcast reel", style = MaterialTheme.typography.headlineSmall)
        WeightConfirmCard(item = soldItem, onConfirm = { _, _, _, _ -> })
        SectionHeader(label = "Rates", channel = CrateTheme.colors.pricing.base)
        rates.forEach { rate ->
            RateRow(rate = rate, onBuy = {}, cheapest = rate.rateId == "r1")
        }
    }
}

@Composable
private fun InboxScene() {
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SectionHeader(label = "Buyer messages", channel = CrateTheme.colors.attention.base)
        messages.forEach { message -> MessageCard(message = message, onResolve = {}) }
    }
}

// --- Fixtures (no photos → no network; Coil never fires) ---

private val templatedDraft = ItemDto(
    id = "draft-1",
    title = "Shimano Curado 200K Baitcast Reel 7.4:1 — Excellent",
    description = "Smooth drag, minor handle wear. Includes original box. From a smoke-free home.",
    brand = "Shimano",
    model = "Curado 200K",
    condition = "like_new",
    status = "draft",
    quickSalePrice = "89.00",
    patientPrice = "104.50",
    chosenPrice = "89.00",
    templateId = "tpl-7",
    createdAt = "2026-07-25T14:03:00Z",
    processedAt = "2026-07-25T14:04:12Z",
    photos = emptyList<ItemPhotoDto>(),
)

private val lowConfidenceDraft = ItemDto(
    id = "draft-2",
    title = "Vintage cast iron skillet 10.25 in",
    description = "Unmarked vintage skillet, smooth cooking surface.",
    condition = "good",
    status = "draft",
    createdAt = "2026-07-25T14:06:00Z",
    processedAt = "2026-07-25T14:07:40Z",
    scanError = "low_confidence",
)

private val soldItem = ItemDto(
    id = "item-9",
    title = "Shimano Curado 200K baitcast reel",
    description = "Smooth drag, minor handle wear. Includes original box.",
    brand = "Shimano",
    model = "Curado 200K",
    condition = "like_new",
    status = "sold",
    quickSalePrice = "89.00",
    patientPrice = "104.50",
    chosenPrice = "94.05",
    ebayListingId = "1100000123",
    weightOzEst = "11.50",
    dimsInEst = mapOf("l" to 8.0, "w" to 6.0, "h" to 4.0),
    weightConfirmed = false,
    templateId = "tpl-7",
    dateListed = "2026-07-10T16:00:00Z",
    createdAt = "2026-07-10T15:12:00Z",
    processedAt = "2026-07-10T15:13:30Z",
)

private val priceHistory = listOf(
    PriceEventDto(
        id = "pe-1",
        oldPrice = "104.50",
        newPrice = "94.05",
        reason = "auto_drop",
        createdAt = "2026-07-24T08:00:00Z",
    ),
)

private val sale = SaleDto(
    id = "sale-1",
    itemId = "item-9",
    ebayOrderId = "12-34567-89012",
    salePrice = "94.05",
    fees = "12.68",
    saleDate = "2026-07-25T02:11:00Z",
    buyerUsername = "reelcollector88",
    buyerAddress = buildJsonObject {
        put("name", JsonPrimitive("R. Collector"))
        put("city", JsonPrimitive("Grand Rapids"))
        put("stateOrProvince", JsonPrimitive("MI"))
        put("postalCode", JsonPrimitive("49503"))
    },
    shipStatus = "pending",
)

private val rates = listOf(
    RateDto(rateId = "r1", provider = "USPS", service = "Ground Advantage", amount = "6.84", estimatedDays = 3),
    RateDto(rateId = "r2", provider = "UPS", service = "Ground Saver", amount = "8.12", estimatedDays = 4),
    RateDto(rateId = "r3", provider = "USPS", service = "Priority Mail", amount = "9.75", estimatedDays = 2),
)

private val messages = listOf(
    MessageDto(
        id = "m1",
        itemId = "item-9",
        messageType = "question",
        content = "Does the reel come with the original box and papers?",
        flaggedAt = "2026-07-24T19:30:00Z",
        resolved = false,
    ),
    MessageDto(
        id = "m2",
        itemId = null,
        messageType = "return_request",
        content = "Item arrived with a cracked side plate — requesting a return.",
        flaggedAt = "2026-07-23T11:02:00Z",
        resolved = false,
    ),
    MessageDto(
        id = "m3",
        itemId = "item-9",
        messageType = "other",
        content = "Thanks for the fast shipping!",
        flaggedAt = "2026-07-22T09:15:00Z",
        resolved = true,
    ),
)
