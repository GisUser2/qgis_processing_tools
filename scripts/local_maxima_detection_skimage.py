# --------------------------------------------------
# Author: GisUser2
# Version: 0.1.2
# Created with: QGIS 3.40.3
# Mar 2025
# --------------------------------------------------
"""
QGIS Processing Algorithm for Local Maxima Detection in Raster Data (skimage)

Requirements:
- Python packages: numpy, rasterio, scikit-image
- QGIS version: 3.40 or newer
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingException,
    QgsRasterBlock
)
from qgis.PyQt.QtCore import QCoreApplication
import numpy as np
import importlib.util
import subprocess
import sys

class LocalMaximaDetection(QgsProcessingAlgorithm):
    """
    Identifies local maxima in raster data using a neighborhood-based approach.
    
    This algorithm detects peaks in raster values by analyzing pixel neighborhoods.
    Suitable for elevation models, heatmaps, and other continuous rasters.
    
    Inputs:
        - Input Raster Layer: Source raster data
        - Neighborhood Size: Minimum distance between detected peaks (in pixels)
    
    Output:
        - Binary raster layer with maxima marked as 255 (white)
    """
    
    # Algorithm parameters
    INPUT_LAYER = 'INPUT_LAYER'
    NEIGHBORHOOD_SIZE = 'NEIGHBORHOOD_SIZE'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def tr(self, text):
        """Provides translation support for UI strings"""
        return QCoreApplication.translate('LocalMaximaDetection', text)

    def createInstance(self):
        """Required factory method to create new algorithm instances"""
        return LocalMaximaDetection()

    def checkDependencies(self, feedback):
        """
        Verifies and installs required Python packages.
        
        Raises:
            QgsProcessingException: If installation fails
        """
        required = {'rasterio': 'rasterio', 'skimage': 'scikit-image'}
        to_install = []

        # Check for missing packages
        for module, package in required.items():
            if not importlib.util.find_spec(module):
                to_install.append(package)

        # Install missing packages
        if to_install:
            feedback.pushInfo(self.tr(f"Installing required packages: {', '.join(to_install)}"))
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', *to_install],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT
                )
            except subprocess.CalledProcessError as e:
                raise QgsProcessingException(
                    self.tr("Package installation failed. Error code: ") + str(e.returncode)
                )

            # Verify installation
            for module in required.keys():
                if not importlib.util.find_spec(module):
                    raise QgsProcessingException(
                        self.tr(f"Critical error: {module} could not be installed automatically")
                    )

    def initAlgorithm(self, config=None):
        """Defines algorithm parameters and UI configuration"""
        
        # Input raster layer parameter
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_LAYER,
            self.tr('Input Raster Layer'),
            optional=False
        ))
        
        # Neighborhood size parameter
        self.addParameter(QgsProcessingParameterNumber(
            self.NEIGHBORHOOD_SIZE,
            self.tr('Neighborhood Size'),
            defaultValue=3,
            minValue=1,
            maxValue=15,
            type=QgsProcessingParameterNumber.Integer
        ))
        
        # Output raster parameter
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_LAYER,
            self.tr('Output Raster Layer')
        ))

    def processAlgorithm(self, parameters, context, feedback):
        """
        Executes the core processing logic.
        """
        try:
            # Check and install dependencies
            self.checkDependencies(feedback)
            
            # Import required modules after installation
            from skimage.feature import peak_local_max
            import rasterio
            from rasterio.transform import from_origin

            # Extract input parameters from QGIS
            input_layer = self.parameterAsRasterLayer(parameters, self.INPUT_LAYER, context)
            neighborhood_size = self.parameterAsInt(parameters, self.NEIGHBORHOOD_SIZE, context)
            output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_LAYER, context)

            # Read raster data using QGIS provider
            provider = input_layer.dataProvider()
            
            # Get raster block (single band processing)
            block = provider.block(1, input_layer.extent(), input_layer.width(), input_layer.height())
            
            if not block.isValid():
                raise QgsProcessingException("Invalid raster data block")

            # Convert QGIS raster block to NumPy array for processing
            raster_data = block.as_numpy()

            # Detect local maxima using scikit-image
            coordinates = peak_local_max(
                raster_data,
                min_distance=neighborhood_size,
                exclude_border=False
            )

            # Create binary output raster where maxima are 255
            local_max = np.zeros_like(raster_data, dtype=np.uint8)
            local_max[tuple(coordinates.T)] = 255

            # Create georeferencing transform for output
            transform = from_origin(
                input_layer.extent().xMinimum(),
                input_layer.extent().yMaximum(),
                input_layer.rasterUnitsPerPixelX(),
                input_layer.rasterUnitsPerPixelY()
            )

            # Write output raster with proper georeference
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=input_layer.height(),
                width=input_layer.width(),
                count=1,
                dtype=rasterio.uint8,
                crs=input_layer.crs().toWkt(),
                transform=transform
            ) as dst:
                dst.write(local_max, 1)

            return {self.OUTPUT_LAYER: output_path}

        except Exception as e:
            feedback.reportError(self.tr(f"Error: {str(e)}"), fatalError=True)
            raise QgsProcessingException(str(e))


    def name(self):
        """Unique algorithm identifier (lowercase with underscores)"""
        return 'local_maxima_detector'

    def displayName(self):
        """User-friendly algorithm name"""
        return self.tr('Local Maxima Detection (scikit-image)')
        
    def shortHelpString(self) -> str:
        """
        Returns a localized short helper string for the algorithm.
        
        <h3>Local Maxima Detection Algorithm</h3>
        
        <b>Purpose:</b><br>
        Identifies local maxima in raster data using a neighborhood-based approach. 
        Suitable for finding peaks in elevation models, heatmaps, and other continuous surfaces.
        
        <b>How it works:</b><ul>
        <li>Applies a maximum filter to find candidate peaks</li>
        <li>Compares original values with filtered results</li>
        <li>Returns positions where original values match maximum filtered values</li>
        </ul>
        
        <b>Inputs:</b><ul>
        <li>Input Raster: Source data (single band, numeric values)</li>
        <li>Neighborhood Size: Minimum distance between peaks (1-15 pixels)</li>
        </ul>
        
        <b>Output:</b><ul>
        <li>Binary raster with maxima marked as 255 (white pixels)</li>
        </ul>
        
        <b>Parameters:</b><br>
        • Neighborhood Size: Controls sensitivity (higher = fewer peaks)<br>
        
        <b>Usage notes:</b><ul>
        <li>Works best with smoothed data - preprocess noisy inputs</li>
        <li>For DEMs, combine with slope analysis for better results</li>
        <li>Output coordinate system matches input layer</li>
        </ul>
        
        Requires scikit-image and rasterio Python packages.
        """
        return self.tr(self.__doc__)

    def group(self):
        """Category for algorithm organization"""
        return self.tr('Spatial Analysis')

    def groupId(self):
        """Unique category identifier"""
        return 'spatial_analysis'

    def version(self):
        """Algorithm versioning"""
        return '0.1'
