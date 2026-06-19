#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Standalone CLI script to run TSM models based on a JSON configuration file.
This script can be executed from the command line without the QGIS interface.
"""

import os
import sys
import json
import argparse
import traceback
from datetime import datetime

# Add the parent directory to sys.path so we can import the plugin modules
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Import required modules from the TSM plugin
from tsm_settings import Config
from PopulationSIM_plugin import PopulatioSIMDialog
from SkimmyDialog_plugin import FLSkim
from SDT_residentDialog_plugin import SDTResidentModel
from SDT_visitorDialog_plugin import SDTVisitorModel
from LDT_residentDialog_plugin import LDTResidentModel
from LDT_visitorDialog_plugin import LDTVisitorModel
from trip_list2table_Dialog_Plugin import ConvertTripListtoTable
from TSMAssignDialog_plugin import TSMAssignDialog
from Subarea_Assign_Dialog_plugin import Subarea_AssignDialog
from tsm_linkConsolidator_plugin_dialog import TsmNetManDialog
from tsm_subarea_plugin_dialog import TsmSubareaExtDialogX

def setup_logging(log_file=None):
    """Set up logging to both console and file if specified."""
    import logging
    
    # Create logger
    logger = logging.getLogger('tsm_cli')
    logger.setLevel(logging.INFO)
    
    # Create console handler and set level
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    
    # Add console handler to logger
    logger.addHandler(ch)
    
    # Add file handler if log file is specified
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    
    return logger

def load_config(config_file):
    """Load the configuration from a JSON file."""
    try:
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        return config_data
    except Exception as e:
        logger.error(f"Failed to load configuration file: {e}")
        return None

def run_model(model_name, logger):
    """Run a specific model based on its name."""
    try:
        logger.info(f"Starting to run model: {model_name}")
        
        if model_name == 'many_to_one':
            dialog = TsmNetManDialog()
            dialog.run_Many2One_script()
        elif model_name == 'PopSIM':
            dialog = PopulatioSIMDialog()
            result = dialog.run_popsim_script()
            if not result:
                logger.error(f"Failed to run PopSIM")
                return False
        elif model_name == 'FL_skimmy':
            dialog = FLSkim()
            result = dialog.run_Skimmy()
            if not result:
                logger.error(f"Failed to run Skimmy")
                return False
        elif model_name == 'SDT_resident':
            dialog = SDTResidentModel()
            result = dialog.run_SDT_resident()
            if not result:
                logger.error(f"Failed to run SDT Resident Model")
                return False
        elif model_name == 'SDT_visitor':
            dialog = SDTVisitorModel()
            result = dialog.run_SDT_visitor()
            if not result:
                logger.error(f"Failed to run SDT Visitor Model")
                return False
        elif model_name == 'LDT_resident':
            dialog = LDTResidentModel()
            result = dialog.run_LDT_resident()
            if not result:
                logger.error(f"Failed to run LDT Resident Model")
                return False
        elif model_name == 'LDT_visitor':
            dialog = LDTVisitorModel()
            result = dialog.run_LDT_visitor()
            if not result:
                logger.error(f"Failed to run LDT Visitor Model")
                return False
        elif model_name == 'TripList2Table':
            dialog = ConvertTripListtoTable()
            result = dialog.run_trip_table()
            if not result:
                logger.error(f"Failed to run Trip List to Table")
                return False
        elif model_name == 'tsm_assign':
            dialog = TSMAssignDialog()
            result = dialog.run_TSM_assignment()
            if not result:
                logger.error(f"Failed to run TSM Assignment")
                return False
        elif model_name == 'SubareaAssignDialog':
            dialog = Subarea_AssignDialog()
            result = dialog.run_subarea_assignment()
            if not result:
                logger.error(f"Failed to run Subarea Assignment")
                return False
        elif model_name == 'tsm_subarea_extractor':
            dialog = TsmSubareaExtDialogX()
            result = dialog.run_extraction()
            if not result:
                logger.error(f"Failed to run Subarea Extractor")
                return False
        else:
            logger.error(f"Unknown model: {model_name}")
            return False
        
        logger.info(f"Successfully completed model: {model_name}")
        return True
    except Exception as e:
        logger.error(f"Error running {model_name}: {e}")
        logger.error(traceback.format_exc())
        return False

def main():
    """Main function to parse arguments and run models."""
    parser = argparse.ArgumentParser(description='Run TSM models from a configuration file.')
    parser.add_argument('config', help='Path to the JSON configuration file')
    parser.add_argument('--log', help='Path to log file (optional)')
    parser.add_argument('--continue-on-error', action='store_true', 
                      help='Continue running subsequent models if one fails')
    args = parser.parse_args()
    
    # Setup logging
    global logger
    if args.log:
        logger = setup_logging(args.log)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(script_dir, f"tsm_run_{timestamp}.log")
        logger = setup_logging(log_file)
    
    logger.info("Starting TSM Model CLI runner")
    
    # Load the configuration
    config_data = load_config(args.config)
    if not config_data:
        logger.error("Failed to load configuration. Exiting.")
        sys.exit(1)
    
    # Load settings into Config
    settings = Config()
    plugin_dir = os.path.dirname(__file__).replace("\\", "/")
    settings.set("plugin_dir", plugin_dir)
    
    # Apply configuration settings
    if 'settings' in config_data:
        for key, value in config_data['settings'].items():
            settings.set(key, value)
    
    # Run models
    if 'models_to_run' in config_data:
        models_to_run = config_data['models_to_run']
        logger.info(f"Models to run: {', '.join(models_to_run)}")
        
        success_count = 0
        failure_count = 0
        
        for model in models_to_run:
            success = run_model(model, logger)
            if success:
                success_count += 1
            else:
                failure_count += 1
                if not args.continue_on_error:
                    logger.error(f"Stopping due to failure in {model}. Use --continue-on-error to run all models.")
                    break
        
        logger.info(f"Completed run. Successful models: {success_count}, Failed models: {failure_count}")
    else:
        logger.error("No models specified in configuration file")
        sys.exit(1)

if __name__ == "__main__":
    main()
