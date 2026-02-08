# Configuration file for SpectroChemPy::PlotPreferences

c = get_config()  # noqa

#------------------------------------------------------------------------------
# PlotPreferences(MetaConfigurable) configuration
#------------------------------------------------------------------------------
## Options for Matplotlib

## 0 to disable; values in the range 10000 to 100000 can improve speed
#                                   slightly and prevent an Agg rendering failure when plotting very large data sets,
#                                   especially if they are very gappy. It may cause minor artifacts, though. A value of
#                                   20000 is probably a good starting point.
#  Default: 20000
# c.PlotPreferences.agg_path_chunksize = 20000

## antialiased option for surface plot
#  Default: True
# c.PlotPreferences.antialiased = True

## display grid on 3d axes
#  Default: True
# c.PlotPreferences.axes3d_grid = True

## How to scale axes limits to the data. Use "data" to use data
#      limits,
#                                      plus some margin. Use "round_number" move to the nearest "round" number
#  Default: 'data'
# c.PlotPreferences.axes_autolimit_mode = 'data'

## whether axis gridlines and ticks are below
#                            the axes elements (lines, text, etc)
#  Default: True
# c.PlotPreferences.axes_axisbelow = True

## axes edge color
#  Default: 'black'
# c.PlotPreferences.axes_edgecolor = 'black'

## axes background color
#  Default: 'F0F0F0'
# c.PlotPreferences.axes_facecolor = 'F0F0F0'

## use scientific notation if log10 of the axis range is smaller than the first
#  or larger than the second
#  Default: (-5, 6)
# c.PlotPreferences.axes_formatter_limits = (-5, 6)

## When useoffset is True, the offset will be used when it can
#                                                remove at least this number of significant digits from tick labels.
#  Default: 4
# c.PlotPreferences.axes_formatter_offset_threshold = 4

## When True, format tick labels according to the user"s locale.
#                                         For example, use "," as a decimal separator in the fr_FR locale.
#  Default: False
# c.PlotPreferences.axes_formatter_use_locale = False

## When True, use mathtext for scientific notation.
#  Default: False
# c.PlotPreferences.axes_formatter_use_mathtext = False

## If True, the tick label formatter will default to labeling ticks
#                                      relative to an offset when the data range is small compared to the minimum
#                                      absolute value of the data.
#  Default: False
# c.PlotPreferences.axes_formatter_useoffset = False

## display grid or not
#  Default: False
# c.PlotPreferences.axes_grid = False

#  Default: 'both'
# c.PlotPreferences.axes_grid_axis = 'both'

#  Default: 'major'
# c.PlotPreferences.axes_grid_which = 'major'

#  Default: 'black'
# c.PlotPreferences.axes_labelcolor = 'black'

## space between label and axis
#  Default: 4.0
# c.PlotPreferences.axes_labelpad = 4.0

## fontsize of the x any y labels
#  Default: 10.0
# c.PlotPreferences.axes_labelsize = 10.0

## weight of the x and y labels
#  Default: 'normal'
# c.PlotPreferences.axes_labelweight = 'normal'

## edge linewidth
#  Default: 0.8
# c.PlotPreferences.axes_linewidth = 0.8

## color cycle for plot lines as list of string colorspecs: single letter,
#                              long name, or web-style hex
#  Default: "cycler('color', ['007200', '009E73', 'D55E00', 'CC79A7', 'F0E442', '56B4E9'])"
# c.PlotPreferences.axes_prop_cycle = "cycler('color', ['007200', '009E73', 'D55E00', 'CC79A7', 'F0E442', '56B4E9'])"

#  Default: True
# c.PlotPreferences.axes_spines_bottom = True

#  Default: True
# c.PlotPreferences.axes_spines_left = True

#  Default: True
# c.PlotPreferences.axes_spines_right = True

#  Default: True
# c.PlotPreferences.axes_spines_top = True

## pad between axes and title in points
#  Default: 5.0
# c.PlotPreferences.axes_titlepad = 5.0

## fontsize of the axes title
#  Default: 14.0
# c.PlotPreferences.axes_titlesize = 14.0

## font weight for axes title
#  Default: 'normal'
# c.PlotPreferences.axes_titleweight = 'normal'

## at the top, no autopositioning.
#  Default: 1.0
# c.PlotPreferences.axes_titley = 1.0

## use unicode for the minus symbol rather than hyphen. See
#                                  http://en.wikipedia.org/wiki/Plus_and_minus_signs#Character_codes
#  Default: True
# c.PlotPreferences.axes_unicode_minus = True

## x margin. See `axes.Axes.margins`
#  Default: 0.05
# c.PlotPreferences.axes_xmargin = 0.05

## y margin See `axes.Axes.margins`
#  Default: 0.05
# c.PlotPreferences.axes_ymargin = 0.05

## ccount (steps in the column mode) for surface plot
#  Default: 50
# c.PlotPreferences.ccount = 50

## Show color bar for 2D plots
#  Default: False
# c.PlotPreferences.colorbar = False

## A colormap name, gray etc...  (equivalent to image_cmap
#  Choices: any of ['magma', 'inferno', 'plasma', 'viridis', 'cividis', 'twilight', 'twilight_shifted', 'turbo', 'berlin', 'managua', 'vanimo', 'Blues', 'BrBG', 'BuGn', 'BuPu', 'CMRmap', 'GnBu', 'Greens', 'Greys', 'OrRd', 'Oranges', 'PRGn', 'PiYG', 'PuBu', 'PuBuGn', 'PuOr', 'PuRd', 'Purples', 'RdBu', 'RdGy', 'RdPu', 'RdYlBu', 'RdYlGn', 'Reds', 'Spectral', 'Wistia', 'YlGn', 'YlGnBu', 'YlOrBr', 'YlOrRd', 'afmhot', 'autumn', 'binary', 'bone', 'brg', 'bwr', 'cool', 'coolwarm', 'copper', 'cubehelix', 'flag', 'gist_earth', 'gist_gray', 'gist_heat', 'gist_ncar', 'gist_rainbow', 'gist_stern', 'gist_yarg', 'gnuplot', 'gnuplot2', 'gray', 'hot', 'hsv', 'jet', 'nipy_spectral', 'ocean', 'pink', 'prism', 'rainbow', 'seismic', 'spring', 'summer', 'terrain', 'winter', 'Accent', 'Dark2', 'Paired', 'Pastel1', 'Pastel2', 'Set1', 'Set2', 'Set3', 'tab10', 'tab20', 'tab20b', 'tab20c', 'grey', 'gist_grey', 'gist_yerg', 'Grays', 'magma_r', 'inferno_r', 'plasma_r', 'viridis_r', 'cividis_r', 'twilight_r', 'twilight_shifted_r', 'turbo_r', 'berlin_r', 'managua_r', 'vanimo_r', 'Blues_r', 'BrBG_r', 'BuGn_r', 'BuPu_r', 'CMRmap_r', 'GnBu_r', 'Greens_r', 'Greys_r', 'OrRd_r', 'Oranges_r', 'PRGn_r', 'PiYG_r', 'PuBu_r', 'PuBuGn_r', 'PuOr_r', 'PuRd_r', 'Purples_r', 'RdBu_r', 'RdGy_r', 'RdPu_r', 'RdYlBu_r', 'RdYlGn_r', 'Reds_r', 'Spectral_r', 'Wistia_r', 'YlGn_r', 'YlGnBu_r', 'YlOrBr_r', 'YlOrRd_r', 'afmhot_r', 'autumn_r', 'binary_r', 'bone_r', 'brg_r', 'bwr_r', 'cool_r', 'coolwarm_r', 'copper_r', 'cubehelix_r', 'flag_r', 'gist_earth_r', 'gist_gray_r', 'gist_heat_r', 'gist_ncar_r', 'gist_rainbow_r', 'gist_stern_r', 'gist_yarg_r', 'gnuplot_r', 'gnuplot2_r', 'gray_r', 'hot_r', 'hsv_r', 'jet_r', 'nipy_spectral_r', 'ocean_r', 'pink_r', 'prism_r', 'rainbow_r', 'seismic_r', 'spring_r', 'summer_r', 'terrain_r', 'winter_r', 'Accent_r', 'Dark2_r', 'Paired_r', 'Pastel1_r', 'Pastel2_r', 'Set1_r', 'Set2_r', 'Set3_r', 'tab10_r', 'tab20_r', 'tab20b_r', 'tab20c_r', 'grey_r', 'gist_grey_r', 'gist_yerg_r', 'Grays_r']
#  Default: 'viridis'
# c.PlotPreferences.colormap = 'viridis'

## Transparency of the contours
#  Default: 1.0
# c.PlotPreferences.contour_alpha = 1.0

## True | False | legacy
#  Choices: any of [True, False, 'legacy']
#  Default: True
# c.PlotPreferences.contour_corner_mask = True

## dashed | solid
#  Choices: any of ['dashed', 'solid']
#  Default: 'dashed'
# c.PlotPreferences.contour_negative_linestyle = 'dashed'

## Fraction of the maximum for starting contour levels
#  Default: 0.05
# c.PlotPreferences.contour_start = 0.05

#  Default: '%b %d %Y'
# c.PlotPreferences.date_autoformatter_day = '%b %d %Y'

#  Default: '%H:%M:%S'
# c.PlotPreferences.date_autoformatter_hour = '%H:%M:%S'

#  Default: '%H:%M:%S.%f'
# c.PlotPreferences.date_autoformatter_microsecond = '%H:%M:%S.%f'

#  Default: '%H:%M:%S.%f'
# c.PlotPreferences.date_autoformatter_minute = '%H:%M:%S.%f'

#  Default: '%b %Y'
# c.PlotPreferences.date_autoformatter_month = '%b %Y'

#  Default: '%H:%M:%S.%f'
# c.PlotPreferences.date_autoformatter_second = '%H:%M:%S.%f'

#  Default: '%Y'
# c.PlotPreferences.date_autoformatter_year = '%Y'

## length of end cap on error bars in pixels
#  Default: 1.0
# c.PlotPreferences.errorbar_capsize = 1.0

## When True, automatically adjust subplot parameters to make the plot fit the
#                               figure
#  Default: True
# c.PlotPreferences.figure_autolayout = True

## figure dots per inch
#  Default: 96.0
# c.PlotPreferences.figure_dpi = 96.0

## figure edgecolor
#  Default: 'white'
# c.PlotPreferences.figure_edgecolor = 'white'

## figure facecolor; 0.75 is scalar gray
#  Default: 'white'
# c.PlotPreferences.figure_facecolor = 'white'

## figure size in inches
#  Default: (6, 4)
# c.PlotPreferences.figure_figsize = (6, 4)

## Show figure frame
#  Default: True
# c.PlotPreferences.figure_frameon = True

## The maximum number of figures to open through the pyplot
#      interface before emitting a warning. If less than one this feature is disabled.
#  Default: 30
# c.PlotPreferences.figure_max_open_warning = 30

## the bottom of the subplots of the figure
#  Default: 0.12
# c.PlotPreferences.figure_subplot_bottom = 0.12

## the amount of height reserved for white space between subplots,
#                                    expressed as a fraction of the average axis height
#  Default: 0.0
# c.PlotPreferences.figure_subplot_hspace = 0.0

## the left side of the subplots of the figure
#  Default: 0.15
# c.PlotPreferences.figure_subplot_left = 0.15

## the right side of the subplots of the figure
#  Default: 0.95
# c.PlotPreferences.figure_subplot_right = 0.95

## the top of the subplots of the figure
#  Default: 0.98
# c.PlotPreferences.figure_subplot_top = 0.98

## the amount of width reserved for blank space between subplots,
#                                    expressed as a fraction of the average axis width
#  Default: 0.0
# c.PlotPreferences.figure_subplot_wspace = 0.0

## size of the figure title (Figure.suptitle())
#  Default: 12.0
# c.PlotPreferences.figure_titlesize = 12.0

## weight of the figure title
#  Default: 'normal'
# c.PlotPreferences.figure_titleweight = 'normal'

## sans-serif|serif|cursive|monospace|fantasy
#  Choices: any of ['sans-serif', 'serif', 'cursive', 'monospace', 'fantasy']
#  Default: 'sans-serif'
# c.PlotPreferences.font_family = 'sans-serif'

## The default fontsize. Special text sizes can be defined relative to font.size,
#                        using the following values: xx-small, x-small, small, medium, large, x-large, xx-large,
#                        larger, or smaller
#  Default: 10.0
# c.PlotPreferences.font_size = 10.0

## normal (or roman), italic or oblique
#  Choices: any of ['normal', 'roman', 'italic', 'oblique']
#  Default: 'normal'
# c.PlotPreferences.font_style = 'normal'

#  Choices: any of ['normal', 'small-caps']
#  Default: 'normal'
# c.PlotPreferences.font_variant = 'normal'

## 100|200|300|normal or 400|500|600|bold or 700|800|900|bolder|lighter
#  Choices: any of [100, 200, 300, 'normal', 400, 500, 600, 'bold', 700, 800, 900, 'bolder', 'lighter']
#  Default: 'normal'
# c.PlotPreferences.font_weight = 'normal'

## transparency, between 0.0 and 1.0
#  Default: 1.0
# c.PlotPreferences.grid_alpha = 1.0

## grid color
#  Default: '.85'
# c.PlotPreferences.grid_color = '.85'

## solid
#  Choices: any of ['-', '--', '-.', ':', 'None', ' ', '']
#  Default: '-'
# c.PlotPreferences.grid_linestyle = '-'

## in points
#  Default: 0.85
# c.PlotPreferences.grid_linewidth = 0.85

#  Default: 'black'
# c.PlotPreferences.hatch_color = 'black'

#  Default: 1.0
# c.PlotPreferences.hatch_linewidth = 1.0

## The default number of histogram bins.
#       If Numpy 1.11 or later is
#       installed, may also be `auto`
#  Default: traitlets.Undefined
# c.PlotPreferences.hist_bins = traitlets.Undefined

## equal | auto | a number
#  Default: 'equal'
# c.PlotPreferences.image_aspect = 'equal'

## A colormap name, gray etc...
#  Choices: any of ['magma', 'inferno', 'plasma', 'viridis', 'cividis', 'twilight', 'twilight_shifted', 'turbo', 'berlin', 'managua', 'vanimo', 'Blues', 'BrBG', 'BuGn', 'BuPu', 'CMRmap', 'GnBu', 'Greens', 'Greys', 'OrRd', 'Oranges', 'PRGn', 'PiYG', 'PuBu', 'PuBuGn', 'PuOr', 'PuRd', 'Purples', 'RdBu', 'RdGy', 'RdPu', 'RdYlBu', 'RdYlGn', 'Reds', 'Spectral', 'Wistia', 'YlGn', 'YlGnBu', 'YlOrBr', 'YlOrRd', 'afmhot', 'autumn', 'binary', 'bone', 'brg', 'bwr', 'cool', 'coolwarm', 'copper', 'cubehelix', 'flag', 'gist_earth', 'gist_gray', 'gist_heat', 'gist_ncar', 'gist_rainbow', 'gist_stern', 'gist_yarg', 'gnuplot', 'gnuplot2', 'gray', 'hot', 'hsv', 'jet', 'nipy_spectral', 'ocean', 'pink', 'prism', 'rainbow', 'seismic', 'spring', 'summer', 'terrain', 'winter', 'Accent', 'Dark2', 'Paired', 'Pastel1', 'Pastel2', 'Set1', 'Set2', 'Set3', 'tab10', 'tab20', 'tab20b', 'tab20c', 'grey', 'gist_grey', 'gist_yerg', 'Grays', 'magma_r', 'inferno_r', 'plasma_r', 'viridis_r', 'cividis_r', 'twilight_r', 'twilight_shifted_r', 'turbo_r', 'berlin_r', 'managua_r', 'vanimo_r', 'Blues_r', 'BrBG_r', 'BuGn_r', 'BuPu_r', 'CMRmap_r', 'GnBu_r', 'Greens_r', 'Greys_r', 'OrRd_r', 'Oranges_r', 'PRGn_r', 'PiYG_r', 'PuBu_r', 'PuBuGn_r', 'PuOr_r', 'PuRd_r', 'Purples_r', 'RdBu_r', 'RdGy_r', 'RdPu_r', 'RdYlBu_r', 'RdYlGn_r', 'Reds_r', 'Spectral_r', 'Wistia_r', 'YlGn_r', 'YlGnBu_r', 'YlOrBr_r', 'YlOrRd_r', 'afmhot_r', 'autumn_r', 'binary_r', 'bone_r', 'brg_r', 'bwr_r', 'cool_r', 'coolwarm_r', 'copper_r', 'cubehelix_r', 'flag_r', 'gist_earth_r', 'gist_gray_r', 'gist_heat_r', 'gist_ncar_r', 'gist_rainbow_r', 'gist_stern_r', 'gist_yarg_r', 'gnuplot_r', 'gnuplot2_r', 'gray_r', 'hot_r', 'hsv_r', 'jet_r', 'nipy_spectral_r', 'ocean_r', 'pink_r', 'prism_r', 'rainbow_r', 'seismic_r', 'spring_r', 'summer_r', 'terrain_r', 'winter_r', 'Accent_r', 'Dark2_r', 'Paired_r', 'Pastel1_r', 'Pastel2_r', 'Set1_r', 'Set2_r', 'Set3_r', 'tab10_r', 'tab20_r', 'tab20b_r', 'tab20c_r', 'grey_r', 'gist_grey_r', 'gist_yerg_r', 'Grays_r']
#  Default: 'viridis'
# c.PlotPreferences.image_cmap = 'viridis'

## When True, all the images on a set of axes are
#       combined into a single composite image before
#       saving a figure as a vector graphics file,
#       such as a PDF.
#  Default: True
# c.PlotPreferences.image_composite_image = True

## see help(imshow) for options
#  Default: 'antialiased'
# c.PlotPreferences.image_interpolation = 'antialiased'

## the size of the colormap lookup table
#  Default: 256
# c.PlotPreferences.image_lut = 256

## lower | upper
#  Default: 'upper'
# c.PlotPreferences.image_origin = 'upper'

#  Default: True
# c.PlotPreferences.image_resample = True

## Latex preamble for matplotlib outputs
#  
#                               IMPROPER USE OF THIS FEATURE WILL LEAD TO LATEX FAILURES.
#                               preamble is a comma separated
#                               list of LaTeX statements that are included in the LaTeX document preamble.
#                               An example:
#                               text.latex.preamble : \usepackage{bm},\usepackage{euler}
#                               The following packages are always loaded with usetex, so beware of package collisions:
#                               color, geometry, graphicx, type1cm, textcomp. Adobe Postscript (PSSNFS) font packages
#                               may also be loaded, depending on your font settings.
#  Default: '\\usepackage{siunitx}\n                            \\sisetup{detect-all}\n                            \\usepackage{times} # set the normal font here\n                            \\usepackage{sansmath}\n                            # load up the sansmath so that math -> helvet\n                            \\sansmath\n                            '
# c.PlotPreferences.latex_preamble = '\\usepackage{siunitx}\n                            \\sisetup{detect-all}\n                            \\usepackage{times} # set the normal font here\n                            \\usepackage{sansmath}\n                            # load up the sansmath so that math -> helvet\n                            \\sansmath\n                            '

## the border between the axes and legend edge
#  Default: 0.5
# c.PlotPreferences.legend_borderaxespad = 0.5

## border whitespace
#  Default: 0.4
# c.PlotPreferences.legend_borderpad = 0.4

## column separation
#  Default: 0.5
# c.PlotPreferences.legend_columnspacing = 0.5

## background patch boundary color
#  Default: '0.8'
# c.PlotPreferences.legend_edgecolor = '0.8'

## inherit from axes.facecolor; or color spec
#  Default: 'inherit'
# c.PlotPreferences.legend_facecolor = 'inherit'

## if True, use a rounded box for the legend background, else a rectangle
#  Default: True
# c.PlotPreferences.legend_fancybox = True

#  Default: 9.0
# c.PlotPreferences.legend_fontsize = 9.0

## legend patch transparency
#  Default: traitlets.Undefined
# c.PlotPreferences.legend_framealpha = traitlets.Undefined

## if True, draw the legend on a background patch
#  Default: False
# c.PlotPreferences.legend_frameon = False

## the height of the legend handle
#  Default: 0.7
# c.PlotPreferences.legend_handleheight = 0.7

## the length of the legend lines
#  Default: 2.0
# c.PlotPreferences.legend_handlelength = 2.0

## the space between the legend line and legend text
#  Default: 0.1
# c.PlotPreferences.legend_handletextpad = 0.1

## the vertical space between the legend entries
#  Default: 0.2
# c.PlotPreferences.legend_labelspacing = 0.2

#  Default: 'best'
# c.PlotPreferences.legend_loc = 'best'

## the relative size of legend markers vs. original
#  Default: 1.0
# c.PlotPreferences.legend_markerscale = 1.0

## the number of marker points in the legend line
#  Default: 1
# c.PlotPreferences.legend_numpoints = 1

## number of scatter points
#  Default: 1
# c.PlotPreferences.legend_scatterpoints = 1

## if True, give background a shadow effect
#  Default: False
# c.PlotPreferences.legend_shadow = False

## render lines in antialiased (no jaggies)
#  Default: True
# c.PlotPreferences.lines_antialiased = True

## has no affect on plot(); see axes.prop_cycle
#  Default: 'b'
# c.PlotPreferences.lines_color = 'b'

## butt|round|projecting
#  Choices: any of ['butt', 'round', 'projecting', 'butt', 'round', 'projecting']
#  Default: 'butt'
# c.PlotPreferences.lines_dash_capstyle = 'butt'

## miter|round|bevel
#  Choices: any of ['miter', 'round', 'bevel', 'miter', 'round', 'bevel']
#  Default: 'round'
# c.PlotPreferences.lines_dash_joinstyle = 'round'

#  Default: (3.0, 5.0, 1.0, 5.0)
# c.PlotPreferences.lines_dashdot_pattern = (3.0, 5.0, 1.0, 5.0)

#  Default: (6.0, 6.0)
# c.PlotPreferences.lines_dashed_pattern = (6.0, 6.0)

#  Default: (1.0, 3.0)
# c.PlotPreferences.lines_dotted_pattern = (1.0, 3.0)

## solid line
#  Choices: any of ['-', '--', '-.', ':', 'None', ' ', '']
#  Default: '-'
# c.PlotPreferences.lines_linestyle = '-'

## line width in points
#  Default: 0.75
# c.PlotPreferences.lines_linewidth = 0.75

## the default marker
#  Choices: any of ['.', ',', 'o', 'v', '^', '<', '>', '1', '2', '3', '4', '8', 's', 'p', '*', 'h', 'H', '+', 'x', 'D', 'd', '|', '_', 'P', 'X', 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 'None', 'none', ' ', '']
#  Default: 'None'
# c.PlotPreferences.lines_marker = 'None'

## the default markeredgecolor
#  Default: 'auto'
# c.PlotPreferences.lines_markeredgecolor = 'auto'

## the line width around the marker symbol
#  Default: 0.0
# c.PlotPreferences.lines_markeredgewidth = 0.0

## the default markerfacecolor
#  Default: 'auto'
# c.PlotPreferences.lines_markerfacecolor = 'auto'

## markersize, in points
#  Default: 7.0
# c.PlotPreferences.lines_markersize = 7.0

#  Default: False
# c.PlotPreferences.lines_scale_dashes = False

## butt|round|projecting
#  Choices: any of ['butt', 'round', 'projecting']
#  Default: 'round'
# c.PlotPreferences.lines_solid_capstyle = 'round'

## miter|round|bevel
#  Choices: any of ['miter', 'round', 'bevel']
#  Default: 'round'
# c.PlotPreferences.lines_solid_joinstyle = 'round'

## full|left|right|bottom|top|none
#  Choices: any of ['full', 'left', 'right', 'bottom', 'top', 'none']
#  Default: 'full'
# c.PlotPreferences.markers_fillstyle = 'full'

## bold
#  Default: 'dejavusans:bold'
# c.PlotPreferences.mathtext_bf = 'dejavusans:bold'

#  Default: 'cursive'
# c.PlotPreferences.mathtext_cal = 'cursive'

## The default font to use for math. Can be any of the LaTeX font
#      names, including the special name "regular" for the same font used in regular text.
#  Default: 'regular'
# c.PlotPreferences.mathtext_default = 'regular'

## When True, use symbols from the Computer Modern fonts when a
#      symbol
#                                         can not be found in one of the custom math fonts.
#  Default: False
# c.PlotPreferences.mathtext_fallback_to_cm = False

## Should be "dejavusans" (default),
#                                 "dejavuserif", "cm" (Computer Modern), "stix", "stixsans" or "custom"
#  Default: 'dejavusans'
# c.PlotPreferences.mathtext_fontset = 'dejavusans'

## italic
#  Default: 'dejavusans:italic'
# c.PlotPreferences.mathtext_it = 'dejavusans:italic'

#  Default: 'dejavusans'
# c.PlotPreferences.mathtext_rm = 'dejavusans'

#  Default: 'sans\\-serif'
# c.PlotPreferences.mathtext_sf = 'sans\\-serif'

#  Default: 'monospace'
# c.PlotPreferences.mathtext_tt = 'monospace'

## Maximum number of lines to plot in stack plots
#  Default: 1000
# c.PlotPreferences.max_lines_in_stack = 1000

## Default plot methods for 1D datasets
#  Choices: any of ['pen', 'scatter', 'scatter+pen', 'bar']
#  Default: 'pen'
# c.PlotPreferences.method_1D = 'pen'

## Default plot methods for 2D datasets
#  Choices: any of ['map', 'image', 'stack', 'surface', '3D']
#  Default: 'stack'
# c.PlotPreferences.method_2D = 'stack'

## Default plot methods for 3D datasets
#  Choices: any of ['surface']
#  Default: 'surface'
# c.PlotPreferences.method_3D = 'surface'

## Number of contours
#  Default: 50
# c.PlotPreferences.number_of_contours = 50

## Number of X labels
#  Default: 5
# c.PlotPreferences.number_of_x_labels = 5

## Number of Y labels
#  Default: 5
# c.PlotPreferences.number_of_y_labels = 5

## Number of Z labels
#  Default: 5
# c.PlotPreferences.number_of_z_labels = 5

## render patches in antialiased (no jaggies)
#  Default: True
# c.PlotPreferences.patch_antialiased = True

## if forced, or patch is not filled
#  Default: 'black'
# c.PlotPreferences.patch_edgecolor = 'black'

#  Default: '4C72B0'
# c.PlotPreferences.patch_facecolor = '4C72B0'

## True to always use edgecolor
#  Default: False
# c.PlotPreferences.patch_force_edgecolor = False

## edge width in points.
#  Default: 0.3
# c.PlotPreferences.patch_linewidth = 0.3

## When True, simplify paths by removing "invisible" points to reduce file size
#      and
#                           increase rendering speed
#  Default: True
# c.PlotPreferences.path_simplify = True

## The threshold of similarity below which vertices will
#      be removed in
#                                        the simplification process
#  Default: 0.111111111111
# c.PlotPreferences.path_simplify_threshold = 0.111111111111

## May be none, or a 3-tuple of the form (scale, length, randomness). *scale*
#      is the amplitude of the wiggle perpendicular to the line (in pixels). *length* is the length of
#                            the wiggle along the line (in pixels). *randomness* is the factor by which the length is
#                            randomly scaled.
#  Default: 'None'
# c.PlotPreferences.path_sketch = 'None'

## When True, rectilinear axis-aligned paths will be snapped to the nearest pixel
#                      when certain criteria are met. When False, paths will never be snapped.
#  Default: True
# c.PlotPreferences.path_snap = True

## display grid on polar axes
#  Default: True
# c.PlotPreferences.polaraxes_grid = True

## rcount (steps in the row mode) for surface plot
#  Default: 50
# c.PlotPreferences.rcount = 50

## "tight" or "standard". "tight" is
#      incompatible with pipe-based animation backends but will worked with temporary file based ones:
#      e.g. setting animation.writer to ffmpeg will not work, use ffmpeg_file instead
#  Choices: any of ['tight', 'standard']
#  Default: 'standard'
# c.PlotPreferences.savefig_bbox = 'standard'

## default directory in savefig dialog box, leave empty to always use current
#                                  working directory
#  Default: ''
# c.PlotPreferences.savefig_directory = ''

## figure dots per inch or "figure"
#  Default: '300'
# c.PlotPreferences.savefig_dpi = '300'

## figure edgecolor when saving
#  Default: 'white'
# c.PlotPreferences.savefig_edgecolor = 'white'

## figure facecolor when saving
#  Default: 'white'
# c.PlotPreferences.savefig_facecolor = 'white'

## png, ps, pdf, svg
#  Choices: any of ['png', 'ps', 'pdf', 'svg']
#  Default: 'png'
# c.PlotPreferences.savefig_format = 'png'

## when a jpeg is saved, the default quality parameter.
#  Default: 95
# c.PlotPreferences.savefig_jpeg_quality = 95

## Padding to be used when bbox is set to "tight"
#  Default: 0.1
# c.PlotPreferences.savefig_pad_inches = 0.1

## setting that controls whether figures are saved with a transparent
#                                 background by default
#  Default: False
# c.PlotPreferences.savefig_transparent = False

## The default marker type for scatter plots.
#  Choices: any of ['.', ',', 'o', 'v', '^', '<', '>', '1', '2', '3', '4', '8', 's', 'p', '*', 'h', 'H', '+', 'x', 'D', 'd', '|', '_', 'P', 'X', 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 'None', 'none', ' ', '']
#  Default: 'o'
# c.PlotPreferences.scatter_marker = 'o'

## Show projection along x
#  Default: False
# c.PlotPreferences.show_projection_x = False

## Show projection along y
#  Default: False
# c.PlotPreferences.show_projection_y = False

## Show all projections
#  Default: False
# c.PlotPreferences.show_projections = False

## Matplotlib path simplification for improving performance
#  Default: False
# c.PlotPreferences.simplify = False

## Basic matplotlib style to use
#  Default: traitlets.Undefined
# c.PlotPreferences.style = traitlets.Undefined

## Directory where to look for local defined matplotlib styles when they are not
#  in the  standard location
#  Default: ''
# c.PlotPreferences.stylesheets = ''

## If True (default), the text will be antialiased.
#                              This only affects the Agg backend.
#  Default: True
# c.PlotPreferences.text_antialiased = True

#  Default: '.15'
# c.PlotPreferences.text_color = '.15'

## May be one of the
#      following: 'none': Perform no hinting
#                           * 'auto': Use freetype's autohinter
#                           * 'native': Use the hinting information in the font file, if available, and if your freetype
#                              library supports it
#                           * 'either': Use the native hinting information or the autohinter if none is available.
#                           For backward compatibility, this value may also be True === 'auto' or False ===
#                           'none'.
#  Choices: any of ['none', 'auto', 'native', 'either']
#  Default: 'auto'
# c.PlotPreferences.text_hinting = 'auto'

## Specifies the amount of softness for hinting in the horizontal
#      direction. A value of 1 will hint to full pixels. A value of 2 will hint to half pixels etc.
#  Default: 8
# c.PlotPreferences.text_hinting_factor = 8

## use latex for all text handling. The following fonts
#                         are supported through the usual rc parameter settings: new century schoolbook, bookman, times,
#                         palatino, zapf chancery, charter, serif, sans-serif, helvetica, avant garde, courier, monospace,
#                         computer modern roman, computer modern sans serif, computer modern typewriter.
#                         If another font is desired which can loaded using the LaTeX \usepackage command, please inquire
#                         at the matplotlib mailing list
#  Default: False
# c.PlotPreferences.text_usetex = False

## a IANA timezone string, e.g., US/Central or Europe/Paris
#  Default: 'UTC'
# c.PlotPreferences.timezone = 'UTC'

## Use Plotly instead of MatPlotLib for plotting (mode Matplotlib more suitable
#  for printing publication ready figures)
#  Default: False
# c.PlotPreferences.use_plotly = False

## draw ticks on the bottom side
#  Default: True
# c.PlotPreferences.xtick_bottom = True

## color of the tick labels
#  Default: '.15'
# c.PlotPreferences.xtick_color = '.15'

## direction
#  Default: 'out'
# c.PlotPreferences.xtick_direction = 'out'

## fontsize of the tick labels
#  Default: 10.0
# c.PlotPreferences.xtick_labelsize = 10.0

## draw x axis bottom major ticks
#  Default: True
# c.PlotPreferences.xtick_major_bottom = True

## distance to major tick label in points
#  Default: 3.5
# c.PlotPreferences.xtick_major_pad = 3.5

## major tick size in points
#  Default: 3.5
# c.PlotPreferences.xtick_major_size = 3.5

## draw x axis top major ticks
#  Default: True
# c.PlotPreferences.xtick_major_top = True

## major tick width in points
#  Default: 0.8
# c.PlotPreferences.xtick_major_width = 0.8

## draw x axis bottom minor ticks
#  Default: True
# c.PlotPreferences.xtick_minor_bottom = True

## distance to the minor tick label in points
#  Default: 3.4
# c.PlotPreferences.xtick_minor_pad = 3.4

## minor tick size in points
#  Default: 2.0
# c.PlotPreferences.xtick_minor_size = 2.0

## draw x axis top minor ticks
#  Default: True
# c.PlotPreferences.xtick_minor_top = True

## visibility of minor ticks on x-axis
#  Default: False
# c.PlotPreferences.xtick_minor_visible = False

## minor tick width in points
#  Default: 0.6
# c.PlotPreferences.xtick_minor_width = 0.6

## draw ticks on the top side
#  Default: False
# c.PlotPreferences.xtick_top = False

## color of the tick labels
#  Default: '.15'
# c.PlotPreferences.ytick_color = '.15'

## direction
#  Default: 'out'
# c.PlotPreferences.ytick_direction = 'out'

## fontsize of the tick labels
#  Default: 10.0
# c.PlotPreferences.ytick_labelsize = 10.0

## draw ticks on the left side
#  Default: True
# c.PlotPreferences.ytick_left = True

## draw y axis left major ticks
#  Default: True
# c.PlotPreferences.ytick_major_left = True

## distance to major tick label in points
#  Default: 3.5
# c.PlotPreferences.ytick_major_pad = 3.5

## draw y axis right major ticks
#  Default: True
# c.PlotPreferences.ytick_major_right = True

## major tick size in points
#  Default: 3.5
# c.PlotPreferences.ytick_major_size = 3.5

## major tick width in points
#  Default: 0.8
# c.PlotPreferences.ytick_major_width = 0.8

## draw y axis left minor ticks
#  Default: True
# c.PlotPreferences.ytick_minor_left = True

## distance to the minor tick label in points
#  Default: 3.4
# c.PlotPreferences.ytick_minor_pad = 3.4

## draw y axis right minor ticks
#  Default: True
# c.PlotPreferences.ytick_minor_right = True

## minor tick size in points
#  Default: 2.0
# c.PlotPreferences.ytick_minor_size = 2.0

## visibility of minor ticks on y-axis
#  Default: False
# c.PlotPreferences.ytick_minor_visible = False

## minor tick width in points
#  Default: 0.6
# c.PlotPreferences.ytick_minor_width = 0.6

## draw ticks on the right side
#  Default: False
# c.PlotPreferences.ytick_right = False
