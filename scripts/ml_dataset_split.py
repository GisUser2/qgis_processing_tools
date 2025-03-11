from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean)
import os
import random
import numpy as np
import rasterio
from rasterio.windows import Window, transform as window_transform
import logging
import shutil

class GenerateImageTiles(QgsProcessingAlgorithm):
    INPUT_IMAGE = 'INPUT_IMAGE'
    INPUT_MASK = 'INPUT_MASK'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'
    TILE_SIZE = 'TILE_SIZE'
    OVERLAP = 'OVERLAP'
    TRAIN_SPLIT = 'TRAIN_SPLIT'
    VAL_SPLIT = 'VAL_SPLIT'
    TEST_SPLIT = 'TEST_SPLIT'
    REMOVE_EMPTY_TILES = 'REMOVE_EMPTY_TILES'
    REMOVE_BACKGROUND_ONLY_TILES = 'REMOVE_BACKGROUND_ONLY_TILES'

    def initAlgorithm(self, config=None):
        # Define input parameters
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_IMAGE, 'Input Image'))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_MASK, 'Input Mask'))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, 'Output Folder'))
        self.addParameter(QgsProcessingParameterNumber(self.TILE_SIZE, 'Tile Size (px)', defaultValue=512))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP, 'Overlap (px)', defaultValue=128))
        self.addParameter(QgsProcessingParameterNumber(self.TRAIN_SPLIT, 'Train Split (%)', type=QgsProcessingParameterNumber.Double, defaultValue=0.7, minValue=0, maxValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.VAL_SPLIT, 'Validation Split (%)', type=QgsProcessingParameterNumber.Double, defaultValue=0.2, minValue=0, maxValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.TEST_SPLIT, 'Test Split (%)', type=QgsProcessingParameterNumber.Double, defaultValue=0.1, minValue=0, maxValue=1))
        # Add option to remove empty and background-only tiles
        self.addParameter(QgsProcessingParameterBoolean(self.REMOVE_EMPTY_TILES, 'Remove Empty Tiles', defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(self.REMOVE_BACKGROUND_ONLY_TILES, 'Remove Background-Only Tiles', defaultValue=True))

        # Set up logging
        log_path = os.path.join(os.path.expanduser("~"), 'process_log.txt')  # Path to user directory
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', filename=log_path)
        logging.info("Algorithm started.")

    def check_dependencies(self):
        """Check if rasterio is installed, and install it if missing."""
        try:
            import rasterio
        except ImportError:
            feedback.pushInfo("rasterio not found. Installing it automatically.")
            os.system('pip install rasterio')
            import rasterio

    def processAlgorithm(self, parameters, context, feedback):
        # Extract parameters
        image_path = self.parameterAsRasterLayer(parameters, self.INPUT_IMAGE, context).source()
        mask_path = self.parameterAsRasterLayer(parameters, self.INPUT_MASK, context).source()
        output_dir = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        tile_size = self.parameterAsInt(parameters, self.TILE_SIZE, context)
        overlap = self.parameterAsInt(parameters, self.OVERLAP, context)
        train_split = self.parameterAsDouble(parameters, self.TRAIN_SPLIT, context)
        val_split = self.parameterAsDouble(parameters, self.VAL_SPLIT, context)
        test_split = self.parameterAsDouble(parameters, self.TEST_SPLIT, context)
        remove_empty_tiles = self.parameterAsBool(parameters, self.REMOVE_EMPTY_TILES, context)
        remove_background_only_tiles = self.parameterAsBool(parameters, self.REMOVE_BACKGROUND_ONLY_TILES, context)

        stride = tile_size - overlap  # Calculate the stride (step for tiling)

        self.check_dependencies()  # Check dependencies for rasterio

        if not os.path.exists(image_path) or not os.path.exists(mask_path):
            raise ValueError(f"Input files not found: {image_path} or {mask_path}")
        
        if not output_dir:
            raise ValueError("Output folder is not set correctly.")
        
        os.makedirs(output_dir, exist_ok=True)

        def generate_tiles():
            """Generate valid image and mask tiles."""
            with rasterio.open(image_path) as src_img:
                img_array = src_img.read()
                meta_img = src_img.meta.copy()
                transform_img = src_img.transform
                height, width = src_img.height, src_img.width
            with rasterio.open(mask_path) as src_mask:
                mask_array = src_mask.read(1)
                meta_mask = src_mask.meta.copy()

            valid_tiles = []
            for y in range(0, height - tile_size + 1, stride):
                for x in range(0, width - tile_size + 1, stride):
                    tile_img = img_array[:, y:y+tile_size, x:x+tile_size]
                    tile_mask = mask_array[y:y+tile_size, x:x+tile_size]
                    new_transform = window_transform(Window(x, y, tile_size, tile_size), transform_img)

                    # Filter out empty tiles and background-only tiles if the respective flags are set
                    if remove_empty_tiles and np.all(tile_img == 0):  # Skip completely empty tiles
                        continue
                    if remove_background_only_tiles and np.all(tile_mask == 0):  # Skip background-only tiles
                        continue

                    valid_tiles.append({
                        "x": x, "y": y, "tile_img": tile_img, "tile_mask": tile_mask, "transform": new_transform
                    })
            return valid_tiles, meta_img, meta_mask

        # Generate valid tiles
        tiles, meta_img, meta_mask = generate_tiles()
        feedback.pushInfo(f"Total valid tiles extracted: {len(tiles)}")

        random.shuffle(tiles)
        n_total = len(tiles)
        n_train = int(n_total * train_split)
        n_val = int(n_total * val_split)
        train_tiles, val_tiles, test_tiles = tiles[:n_train], tiles[n_train:n_train+n_val], tiles[n_train+n_val:]
        feedback.pushInfo(f"Train: {len(train_tiles)} | Validation: {len(val_tiles)} | Test: {len(test_tiles)}")

        def save_tile(tile_data, meta_img, meta_mask, split, tile_name):
            """Save individual tiles to the output folder."""
            img_out_path = os.path.join(output_dir, split, "images")
            mask_out_path = os.path.join(output_dir, split, "masks")
            os.makedirs(img_out_path, exist_ok=True)
            os.makedirs(mask_out_path, exist_ok=True)

            meta_tile_img = meta_img.copy()
            meta_tile_img.update({"driver": "GTiff", "height": tile_size, "width": tile_size, "transform": tile_data["transform"]})
            meta_tile_mask = meta_mask.copy()
            meta_tile_mask.update({"driver": "GTiff", "height": tile_size, "width": tile_size, "transform": tile_data["transform"]})

            with rasterio.open(os.path.join(img_out_path, f"{tile_name}.tif"), "w", **meta_tile_img) as dst_img:
                dst_img.write(tile_data["tile_img"])
            with rasterio.open(os.path.join(mask_out_path, f"{tile_name}.tif"), "w", **meta_tile_mask) as dst_mask:
                dst_mask.write(tile_data["tile_mask"], 1)

        # Save tiles to respective folders based on splits
        tile_counter = 0
        for split, split_tiles in zip(["train", "val", "test"], [train_tiles, val_tiles, test_tiles]):
            for tile_data in split_tiles:
                save_tile(tile_data, meta_img, meta_mask, split, f"tile_{tile_counter}")
                tile_counter += 1

        feedback.pushInfo("Tiles saved successfully.")
        logging.info("Process completed successfully.")
        return {self.OUTPUT_FOLDER: output_dir}


    def name(self):
        return "generate_image_tiles"
    
    def displayName(self):
        return "Dataset Split"
    
    def group(self):
        return "ML Tools"
    
    def groupId(self):
        return "custom_scripts"
    
    def createInstance(self):
        return GenerateImageTiles()

    def shortHelpString(self):
        return (
            "This algorithm generates image tiles from input raster images and masks. \n"
            "Tiles are generated with specified size, overlap, and splits for training, "
            "validation, and testing datasets. Tiles are saved in the output folder in subdirectories "
            "for each split (train, val, test). Additionally, the option to remove empty or "
            "background-only tiles is available.\n\n"
            
            "Options:\n\n"
            
            "Remove Empty Tiles: Removes tiles with absolutely no content (all pixels are zero).\n"
            "Remove Background_only Tiles: Removes tiles where the only content is background "
            "(even if there are no actual non-background objects in the tile)."
        )
