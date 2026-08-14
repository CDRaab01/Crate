package com.crate.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.ui.theme.CrateTheme
import design.pulse.ui.components.Caption
import design.pulse.ui.components.ChannelDot

/**
 * Apparel item specifics, shared by the review stack and the item detail screen.
 *
 * Crate is archiving a wardrobe well ahead of any eBay keyset, which makes one gap
 * uniquely expensive: size, material and measurements live on the garment's tag and on a
 * tape measure, not in a photo. Once a shirt is folded into a bin, the only way to recover
 * them is to unbox it. The server computes which fields are still missing (missing_hand_only
 * is the urgent subset); this file is the display and edit surface for that.
 */

/** Human labels for the server's field names. */
private val FIELD_LABELS = mapOf(
    "brand" to "Brand",
    "size" to "Size",
    "size_type" to "Size type",
    "department" to "Department",
    "color" to "Color",
    "material" to "Material",
    "style" to "Style",
    "condition" to "Condition",
    "measurements" to "Measurements",
)

internal fun fieldLabel(field: String): String =
    FIELD_LABELS[field] ?: field.replace('_', ' ').replaceFirstChar { it.uppercase() }

/** "Mens · M · Navy · Button-Up" — the at-a-glance garment line, blank for general goods. */
internal fun apparelSummary(item: ItemDto): String =
    if (item.itemKind != "clothing") {
        ""
    } else {
        listOfNotNull(
            item.department?.replace('_', ' '),
            item.size,
            item.color,
            item.style,
        ).joinToString(" · ")
    }

/** "21\" chest · 29\" length" — only the measurements actually taken. */
internal fun measurementSummary(item: ItemDto): String {
    val order = listOf("chest", "length", "sleeve", "shoulder", "waist", "inseam", "rise")
    val taken = item.measurementsIn ?: return ""
    return order.mapNotNull { key ->
        taken[key]?.let { value ->
            val trimmed = if (value % 1.0 == 0.0) value.toInt().toString() else value.toString()
            "$trimmed\" $key"
        }
    }.joinToString(" · ")
}

/**
 * The archive nag: what still needs the physical garment.
 *
 * Deliberately styled on the `attention` channel rather than as an error — a fresh capture
 * legitimately starts incomplete, and the point is to catch it before the item is boxed,
 * not to shout about a broken draft.
 */
@Composable
internal fun ArchiveGapRow(item: ItemDto, modifier: Modifier = Modifier) {
    if (item.missingHandOnly.isEmpty()) return
    val fields = item.missingHandOnly.joinToString(", ") { fieldLabel(it) }
    Row(modifier = modifier, verticalAlignment = Alignment.Top) {
        ChannelDot(color = CrateTheme.colors.attention.base)
        Spacer(Modifier.size(6.dp))
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                "Needs the item in hand: $fields",
                style = MaterialTheme.typography.labelSmall,
                color = CrateTheme.colors.attention.base,
            )
            Caption(text = "Add these before it goes in a bin — a photo can't give them back.")
        }
    }
}

/**
 * Edit sheet for the tag + tape-measure fields, plus where the item is stored.
 *
 * Enum-valued fields are typed free-hand on purpose, matching the existing condition field:
 * the server normalizes shape ("Mens", "Big & Tall", "Long Sleeve" all land correctly) and
 * only 422s on a genuinely unknown value, so a text field is forgiving without being loose.
 */
@Composable
internal fun GarmentDetailsDialog(
    item: ItemDto,
    onSave: (ItemUpdateRequest) -> Unit,
    onCancel: () -> Unit,
) {
    var size by remember { mutableStateOf(item.size ?: "") }
    var sizeType by remember { mutableStateOf(item.sizeType ?: "") }
    var department by remember { mutableStateOf(item.department ?: "") }
    var color by remember { mutableStateOf(item.color ?: "") }
    var material by remember { mutableStateOf(item.material ?: "") }
    var style by remember { mutableStateOf(item.style ?: "") }
    var fit by remember { mutableStateOf(item.fit ?: "") }
    var sleeve by remember { mutableStateOf(item.sleeveLength ?: "") }
    var storage by remember { mutableStateOf(item.storageLocation ?: "") }

    val existing = item.measurementsIn.orEmpty()
    fun initial(key: String) = existing[key]?.let {
        if (it % 1.0 == 0.0) it.toInt().toString() else it.toString()
    } ?: ""
    var chest by remember { mutableStateOf(initial("chest")) }
    var length by remember { mutableStateOf(initial("length")) }
    var sleeveIn by remember { mutableStateOf(initial("sleeve")) }
    var shoulder by remember { mutableStateOf(initial("shoulder")) }
    var waist by remember { mutableStateOf(initial("waist")) }
    var inseam by remember { mutableStateOf(initial("inseam")) }

    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Garment details") },
        text = {
            Column(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier
                    .heightIn(max = 420.dp)
                    .verticalScroll(rememberScrollState()),
            ) {
                Caption(text = "Read straight off the tag — leave blank rather than guessing.")
                OutlinedTextField(size, { size = it }, label = { Text("Size (as printed)") })
                OutlinedTextField(
                    sizeType,
                    { sizeType = it },
                    label = { Text("Size type (regular/petite/plus/big tall/juniors/maternity)") },
                )
                OutlinedTextField(
                    department,
                    { department = it },
                    label = { Text("Department (mens/womens/unisex/boys/girls)") },
                )
                OutlinedTextField(color, { color = it }, label = { Text("Color") })
                OutlinedTextField(material, { material = it }, label = { Text("Material") })
                OutlinedTextField(style, { style = it }, label = { Text("Style") })
                OutlinedTextField(
                    fit,
                    { fit = it },
                    label = { Text("Fit (slim/regular/relaxed/oversized)") },
                )
                OutlinedTextField(
                    sleeve,
                    { sleeve = it },
                    label = { Text("Sleeve (sleeveless/short/three quarter/long)") },
                )

                Spacer(Modifier.size(4.dp))
                Caption(text = "Measurements in inches, garment laid flat.")
                MeasurementField("Chest (pit to pit)", chest) { chest = it }
                MeasurementField("Length", length) { length = it }
                MeasurementField("Sleeve", sleeveIn) { sleeveIn = it }
                MeasurementField("Shoulder", shoulder) { shoulder = it }
                MeasurementField("Waist", waist) { waist = it }
                MeasurementField("Inseam", inseam) { inseam = it }

                Spacer(Modifier.size(4.dp))
                OutlinedTextField(
                    storage,
                    { storage = it },
                    label = { Text("Stored in (e.g. Bin 3)") },
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val measurements = buildMap {
                    chest.toDoubleOrNull()?.let { put("chest", it) }
                    length.toDoubleOrNull()?.let { put("length", it) }
                    sleeveIn.toDoubleOrNull()?.let { put("sleeve", it) }
                    shoulder.toDoubleOrNull()?.let { put("shoulder", it) }
                    waist.toDoubleOrNull()?.let { put("waist", it) }
                    inseam.toDoubleOrNull()?.let { put("inseam", it) }
                }
                onSave(
                    // "" clears server-side, absent leaves untouched — send every field as
                    // typed so emptying one really empties it. An explicitly empty
                    // measurements map clears the tape readings the same way.
                    ItemUpdateRequest(
                        itemKind = "clothing",
                        size = size,
                        sizeType = sizeType,
                        department = department,
                        color = color,
                        material = material,
                        style = style,
                        fit = fit,
                        sleeveLength = sleeve,
                        measurementsIn = measurements,
                        storageLocation = storage,
                    )
                )
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onCancel) { Text("Cancel") } },
    )
}

@Composable
private fun MeasurementField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = { typed ->
            // Digits and a single decimal point only: the server rejects anything it can't
            // read as inches, and a 422 three fields later is a poor way to learn that.
            if (typed.isEmpty() || typed.matches(Regex("^\\d{0,2}(\\.\\d{0,2})?$"))) onChange(typed)
        },
        label = { Text(label) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Decimal,
            imeAction = ImeAction.Next,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}
