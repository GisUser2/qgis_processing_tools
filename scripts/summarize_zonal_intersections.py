# --------------------------------------------------
# Author: GisUser2
# Version: 0.1 (Alpha Version)
# Created with: QGIS 3.40.3
# Description: TODO
# --------------------------------------------------

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsField,
    QgsFields,
    QgsFeatureSink,
    QgsProcessingException,
    QgsProcessing,
    QgsProcessingUtils
)

class SummarizeIntersection(QgsProcessingAlgorithm):
    INPUT_ZONES = 'INPUT_ZONES'
    ZONE_FIELDS = 'ZONE_FIELDS'
    INPUT_CLASSES = 'INPUT_CLASSES'
    CLASS_FIELDS = 'CLASS_FIELDS'
    SUM_FIELDS = 'SUM_FIELDS'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_ZONES,
                'Input Zone Layer',
                types=[QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorLine, QgsProcessing.TypeVectorPoint]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.ZONE_FIELDS,
                'Zone Attributes',
                allowMultiple=True,
                parentLayerParameterName=self.INPUT_ZONES
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_CLASSES,
                'Input Class Layer',
                types=[QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.CLASS_FIELDS,
                'Class Attributes',
                allowMultiple=True,
                optional=True,
                parentLayerParameterName=self.INPUT_CLASSES
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.SUM_FIELDS,
                'Sum Fields',
                allowMultiple=True,
                optional=True,
                parentLayerParameterName=self.INPUT_CLASSES
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                'Output Summary Table',
                type=QgsProcessing.TypeVector
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        zones_source = self.parameterAsSource(parameters, self.INPUT_ZONES, context)
        zone_fields = self.parameterAsFields(parameters, self.ZONE_FIELDS, context)
        classes_source = self.parameterAsSource(parameters, self.INPUT_CLASSES, context)
        class_fields = self.parameterAsFields(parameters, self.CLASS_FIELDS, context)
        sum_fields = self.parameterAsFields(parameters, self.SUM_FIELDS, context)
        
        self.validateGeometries(zones_source, classes_source)

        # Determinar tipos de geometria
        zone_type = QgsWkbTypes.geometryType(zones_source.wkbType())
        class_type = QgsWkbTypes.geometryType(classes_source.wkbType())

        output_fields = QgsFields()
        
        # Campos da zona
        for f in zones_source.fields():
            if f.name() in zone_fields:
                output_fields.append(f)
        
        # Campos da classe
        class_fields_to_add = class_fields if class_fields else []
        for f in classes_source.fields():
            if f.name() in class_fields_to_add:
                output_fields.append(f)
        
        # Adicionar campos condicionalmente
        if zone_type == QgsWkbTypes.PolygonGeometry and class_type == QgsWkbTypes.PolygonGeometry:
            output_fields.append(QgsField('AREA', QVariant.Double))
        
        if class_type == QgsWkbTypes.LineGeometry:
            output_fields.append(QgsField('LENGTH', QVariant.Double))
        
        if class_type == QgsWkbTypes.PointGeometry:
            output_fields.append(QgsField('PNT_COUNT', QVariant.Int))
        
        output_fields.append(QgsField('PERCENTAGE', QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            output_fields,
            QgsWkbTypes.NoGeometry,
            zones_source.sourceCrs()
        )
        
        zones = self.groupFeatures(zones_source, zone_fields)
        classes = self.groupFeatures(classes_source, class_fields) if class_fields else {'ALL': list(classes_source.getFeatures())}
        
        total = len(zones) * len(classes) if zones and classes else 1
        current = 0

        for zone_key, zone_features in zones.items():
            for zone_feature in zone_features:
                zone_geom = zone_feature.geometry()
                total_zone_measure = self.calculateTotalMeasure(zone_geom, zones_source.wkbType())
                
                for class_key, class_features in classes.items():
                    class_measures = {
                        'AREA': 0.0,
                        'LENGTH': 0.0,
                        'PNT_COUNT': 0,
                        'SUM_FIELDS': {field: 0.0 for field in sum_fields}
                    }
                    
                    for class_feature in class_features:
                        class_geom = class_feature.geometry()
                        if zone_geom.intersects(class_geom):
                            intersection = zone_geom.intersection(class_geom)
                            if not intersection.isEmpty():
                                measure = self.calculateMeasure(intersection, zones_source, classes_source)
                                class_measures = self.updateMeasures(class_measures, measure, class_feature, sum_fields)
                                
                    percentage = self.calculatePercentage(class_measures, total_zone_measure, zones_source, classes_source)
                    
                    if not (class_measures['AREA'] or class_measures['LENGTH'] 
                            or class_measures['PNT_COUNT'] or percentage):
                        continue

                    out_feature = QgsFeature(output_fields)
                    attrs = []
                    
                    for field in zone_fields:
                        attrs.append(zone_feature[field])
                    
                    for field in class_fields_to_add:
                        attrs.append(class_feature[field])
                    
                    metrics = []
                    if zone_type == QgsWkbTypes.PolygonGeometry and class_type == QgsWkbTypes.PolygonGeometry:
                        metrics.append(class_measures['AREA'])
                    if class_type == QgsWkbTypes.LineGeometry:
                        metrics.append(class_measures['LENGTH'])
                    if class_type == QgsWkbTypes.PointGeometry:
                        metrics.append(class_measures['PNT_COUNT'])
                    
                    metrics.append(percentage)
                    attrs.extend(metrics)
                    
                    out_feature.setAttributes(attrs)
                    sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
                
                current += 1
                feedback.setProgress(int((current / total) * 100))
        
        return {self.OUTPUT: dest_id}

    def calculateTotalMeasure(self, geometry, wkb_type):
        """Calcula a medida total da geometria da zona (área/comprimento)"""
        geometry_type = QgsWkbTypes.geometryType(wkb_type)
        
        if geometry_type == QgsWkbTypes.PolygonGeometry:
            return geometry.area()
        elif geometry_type == QgsWkbTypes.LineGeometry:
            return geometry.length()
        elif geometry_type == QgsWkbTypes.PointGeometry:
            return 1  # Contagem de pontos
        return 0
    
    def validateGeometries(self, zones, classes):
        zone_type = QgsWkbTypes.geometryType(zones.wkbType())
        class_type = QgsWkbTypes.geometryType(classes.wkbType())
        
        if zone_type == QgsWkbTypes.PointGeometry:
            if class_type in [QgsWkbTypes.PolygonGeometry, QgsWkbTypes.LineGeometry]:
                raise QgsProcessingException("Class features cannot be polygons or lines when zone features are points")
        
        if zone_type == QgsWkbTypes.LineGeometry:
            if class_type == QgsWkbTypes.PolygonGeometry:
                raise QgsProcessingException("Class features cannot be polygons when zone features are lines")
        
        if class_type > zone_type:
            raise QgsProcessingException("Higher dimension class features are not supported for this zone type")
        
    def updateMeasures(self, current_measures, measure, class_feature, sum_fields):
        """Atualiza as métricas acumuladas com base na interseção atual"""
        try:
            # Verificar geometria válida
            if not class_feature.geometry().isGeosValid():
                return current_measures

            # Determinar tipo de geometria da classe
            class_type = QgsWkbTypes.geometryType(class_feature.geometry().wkbType())
            
            # Atualizar medidas principais com verificação de tipo
            if class_type == QgsWkbTypes.PolygonGeometry:
                current_measures['AREA'] += measure if measure else 0.0
            elif class_type == QgsWkbTypes.LineGeometry:
                current_measures['LENGTH'] += measure if measure else 0.0
            elif class_type == QgsWkbTypes.PointGeometry:
                current_measures['PNT_COUNT'] += int(measure) if measure else 0
            
            # Processar campos de soma com tratamento de erros
            if sum_fields:
                for field in sum_fields:
                    if field not in class_feature.fields():
                        continue
                    
                    # Obter valor do atributo com fallback para 0
                    feature_value = float(class_feature[field]) if class_feature[field] else 0.0
                    
                    # Calcular medida total da feature da classe
                    total_class_measure = self.calculateTotalMeasure(
                        class_feature.geometry(),
                        class_feature.geometry().wkbType()
                    )
                    
                    # Calcular proporção com proteção contra divisão por zero
                    proportion = measure / total_class_measure if total_class_measure != 0 else 0.0
                    
                    # Atualizar soma proporcional
                    current_measures['SUM_FIELDS'][field] += feature_value * proportion

            return current_measures

        except Exception as e:
            self.feedback.reportError(f"Erro ao processar feature {class_feature.id()}: {str(e)}")
            return current_measures


    def calculateMeasure(self, geometry, zone_source, class_source):
        zone_type = QgsWkbTypes.geometryType(zone_source.wkbType())
        class_type = QgsWkbTypes.geometryType(class_source.wkbType())
        
        if zone_type == QgsWkbTypes.PolygonGeometry and class_type == QgsWkbTypes.PolygonGeometry:
            return geometry.area()
        elif class_type == QgsWkbTypes.LineGeometry:
            return geometry.length()
        elif class_type == QgsWkbTypes.PointGeometry:
            return 1  # Contagem
        return 0

    def calculatePercentage(self, class_measures, total_zone_measure, zones_source, classes_source):
        zone_type = QgsWkbTypes.geometryType(zones_source.wkbType())
        class_type = QgsWkbTypes.geometryType(classes_source.wkbType())
        
        if zone_type == class_type:
            denominator = total_zone_measure
        else:
            denominator = class_measures['AREA'] if class_type == QgsWkbTypes.PolygonGeometry else class_measures['LENGTH']
        
        if denominator == 0:
            return 0.0
        
        if zone_type == QgsWkbTypes.PolygonGeometry:
            value = class_measures['AREA']
        elif zone_type == QgsWkbTypes.LineGeometry:
            value = class_measures['LENGTH']
        else:
            value = class_measures['PNT_COUNT']
        
        return (value / denominator) * 100

    def groupFeatures(self, source, fields):
        groups = {}
        for feature in source.getFeatures():
            key = tuple(feature[field] for field in fields) if fields else 'ALL'
            if key not in groups:
                groups[key] = []
            groups[key].append(feature)
        return groups

    def name(self):
        return 'summarizeintersection'

    def displayName(self):
        return 'Summarize Zonal Intersections'

    def createInstance(self):
        return SummarizeIntersection()
