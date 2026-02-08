# Configuration file for SpectroChemPy::GeneralPreferences

c = get_config()  # noqa

#------------------------------------------------------------------------------
# GeneralPreferences(MetaConfigurable) configuration
#------------------------------------------------------------------------------
## Preferences that apply to the  `SpectroChemPy` application in general.
#  
#  They should be accessible from the main API.

## Automatic loading of the last project at startup
#  Default: True
# c.GeneralPreferences.autoload_project = True

## Automatic saving of the current project
#  Default: True
# c.GeneralPreferences.autosave_project = True

## Frequency of checking for update
#  Choices: any of ['day', 'week', 'month']
#  Default: 'week'
# c.GeneralPreferences.check_update_frequency = 'week'

## CSV data delimiter
#  Choices: any of [',', ';', '\\t', ' ']
#  Default: ','
# c.GeneralPreferences.csv_delimiter = ','

## Directory where to look for data by default
#  Default: traitlets.Undefined
# c.GeneralPreferences.datadir = traitlets.Undefined

## Last used project
#  Default: traitlets.Undefined
# c.GeneralPreferences.last_project = traitlets.Undefined

## Directory where projects are stored by default
#  Default: traitlets.Undefined
# c.GeneralPreferences.project_directory = traitlets.Undefined

## Display the close project dialog project changing or on application exit
#  Default: True
# c.GeneralPreferences.show_close_dialog = True

## Display info on loading
#  Default: True
# c.GeneralPreferences.show_info_on_loading = True

## Use QT for dialog instead of TK which is the default. If True the PyQt
#  libraries must be installed
#  Default: False
# c.GeneralPreferences.use_qt = False

## Workspace directory by default
#  Default: traitlets.Undefined
# c.GeneralPreferences.workspace = traitlets.Undefined
