"""Constants for the Gaposa integration."""

DOMAIN = "gaposa"
API_KEY = "AIzaSyCBNj_bYZ6VmHU8iNuVmvuj0HQLpv4DTfE"

# Intervalle de mise à jour en secondes (si nécessaire)
UPDATE_INTERVAL = 30

# Calibration constants
CONF_TRAVEL_TIME = "travel_time"
CONF_CALIBRATION_DATA = "calibration_data"
CONF_OPEN_TIME = "open_time"
CONF_CLOSE_TIME = "close_time"
DEFAULT_TRAVEL_TIME = 30  # Default travel time in seconds if not calibrated
DEFAULT_OPEN_TIME = 30    # Default open time in seconds
DEFAULT_CLOSE_TIME = 25   # Default close time in seconds (usually faster due to gravity)
