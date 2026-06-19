# TSM Subarea Extraction GUI Widget User Guide

## Introduction
The Subarea Extraction widget is part of the Turnpike State Model (TSM), designed to efficiently extract subarea networks and associated trip tables. This tool supports managing and maintaining subarea consistency through node crosswalk files across different scenario years.

---

## GUI Overview

### Basic Configuration

#### 1. **Subarea Name**
- **Description:** Defines a unique identifier for the subarea extraction.
- **Interaction:** Enter the subarea name in the provided text field.

#### 2. **Network Layers**
- **Network Link File:** Select the appropriate link layer (LineString).
- **Network Node File:** Select the appropriate node layer (Point).
- **Subarea Boundary File:** Choose the polygon layer representing subarea boundaries.
- **Interaction:** Select layers from the respective dropdown menus.

---

### Additional Options

#### 1. **Use Selected Subarea Polygon**
- **Description:** Allows the selection of specific polygon features for subarea extraction.
- **Interaction:** Check to activate subarea extraction based on currently selected polygons.

#### 2. **Node Consistency Across Years**
- **Description:** Maintains node numbering consistency over multiple scenario years.
- **Interaction:** Check to activate consistency management.
  - **Read Node Crosswalk:** Specify the file path to an existing crosswalk file.
  - **Save Node Crosswalk:** Specify the file path to save a new crosswalk file.

---

### Settings Management

#### Save Settings File
- **Description:** Stores current configurations in a settings file for future use.
- **Interaction:** Click **Browse** to specify the settings file.

---

### Output Configuration

#### Output Directory
- **Description:** Defines the directory to store subarea extraction results.
- **Interaction:** Click **Browse** to select or enter manually.

---

## Execution and Saving

- Click **OK** to run the subarea extraction process.
- Click **Cancel** to exit without running the process.

---

## GUI Screenshot

Below is a visual representation of the Subarea Extraction widget, highlighting critical configuration elements:

![Subarea Extraction GUI Screenshot](path_to_your_screenshot_image_here)

---

## Additional Notes

- Ensure selected input layers are accurate and compatible.
- Regularly update and manage node crosswalk files for accurate long-term scenario analysis.
- Verify the output directory and settings file paths before execution.

