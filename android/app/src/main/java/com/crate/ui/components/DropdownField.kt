package com.crate.ui.components

import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow

/**
 * A pick-one-of-many field for the review screen.
 *
 * `ExposedDropdownMenuBox` rather than a new Pulse component: Spotter, Plate and Cookbook all
 * use it directly for the same job, and matching the siblings beats inventing a shared widget
 * for a pattern the suite already settled.
 *
 * Options carry a display label separate from the wire value because the server owns both —
 * the API validates `big_tall`, a human picks "Big & Tall", and deriving one from the other
 * on the client would mean two places to fix when a label reads badly.
 *
 * @param onOpen fired when the menu is expanded, for options that must be fetched on demand
 *   (eBay category suggestions cost a network call, so they are not loaded for every draft).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DropdownField(
    label: String,
    value: String?,
    options: List<Pair<String, String>>,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "Select…",
    supporting: String? = null,
    onOpen: () -> Unit = {},
) {
    var expanded by remember { mutableStateOf(false) }
    // Fall back to the raw value when it is not in `options`: a draft can legitimately hold a
    // value this build's vocabulary does not list (server added one, app not updated). Showing
    // it beats rendering the field blank, which reads as "nothing set" and invites overwriting.
    val display = options.firstOrNull { it.first == value }?.second ?: value

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = {
            expanded = it
            if (it) onOpen()
        },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = display ?: "",
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            placeholder = { Text(placeholder) },
            supportingText = supporting?.let { { Text(it) } },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier.menuAnchor(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            if (options.isEmpty()) {
                DropdownMenuItem(
                    text = { Text(placeholder) },
                    onClick = {},
                    enabled = false,
                )
            }
            options.forEach { (optionValue, optionLabel) ->
                DropdownMenuItem(
                    text = { Text(optionLabel, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    onClick = {
                        onSelect(optionValue)
                        expanded = false
                    },
                )
            }
        }
    }
}
