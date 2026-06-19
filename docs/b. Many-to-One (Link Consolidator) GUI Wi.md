# Many-to-One (Link Consolidator) GUI Widget User Guide

## Introduction
The Many-to-One tool, colloquially known as the Link Consolidator, streamlines extensive roadway networks used in transportation modeling. It merges multiple links into fewer segments, significantly reducing computational load while preserving essential geometric detail for accurate path distance and travel time calculations.

Link Consolidation converts extensive link and node databases from sources like Navteq, OSM, Google, and Bing Maps into manageable networks suitable for modeling purposes.

---

## GUI Overview

### Scenario Configuration

#### 1. **Scenario Name**
- **Description:** Assign a unique identifier to the consolidation scenario.
- **Interaction:** Enter the scenario name into the text field.

#### 2. **Select Year**
- **Description:** Select the scenario year for the consolidated dataset.
- **Interaction:** Use the dropdown menu to choose the year.

#### 3. **Max Internal Zones**
- **Description:** Define the maximum number of internal zones considered.
- **Interaction:** Enter the maximum number of zones directly into the field (default is 8721).

---

### Input Configuration

#### 1. **GeoMaster Line Layer**
- **Description:** Select the network line (link) layer.
- **Interaction:** Use the dropdown to select the appropriate line layer.

#### 2. **GeoMaster Node Layer**
- **Description:** Select the network node layer.
- **Interaction:** Use the dropdown to select the node layer.

---

### Advanced Options

- **Keep Counts:** Maintain count attributes during consolidation.
- **Turn Off ThruLanes:** Option to disable the consolidation of through lanes.
- **Check Lanes:** Validate the consistency and accuracy of lane attributes.
- **Write Interim Files:** Save interim files created during the consolidation process.
- **Load Output Files:** Automatically load resulting output files into the current GIS session.

---

### Settings and Output

#### Save Settings File
- **Description:** Store current consolidation configuration settings.
- **Interaction:** Click **Browse** to specify or select a file.

#### Output Directory
- **Description:** Choose the directory where consolidated network files will be saved.
- **Interaction:** Click **Browse** to select or enter manually.

---

## Execution and Saving

- Click **OK** to execute the Link Consolidation.
- Click **Cancel** to close without execution.

---

## GUI Screenshot

Below is a visual overview of the Many-to-One (Link Consolidator) widget interface, highlighting essential components and interactions:

![Link Consolidator GUI Screenshot](path_to_your_screenshot_image_here)

---

## Additional Notes

- Ensure selected network layers accurately reflect the current modeling scenario.
- Regularly manage and update consolidation settings files for streamlined repeated operations.
- Review and verify interim files if enabled, to ensure optimal network integrity.

