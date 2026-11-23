"""The delivered models must retain task boundaries, manual input and a real sweep."""
import unittest
from pathlib import Path
from models import load,child,children
from bridge.anylogic import field
from conveyor import by_name
from lr5_revision import param

class LabFiveContract(unittest.TestCase):
    def test_tasks_manual_input_supply_and_capacity(self):
        base=Path(__file__).parent/'templates/models'
        for task,name in [('5.1','Model.alp'),('5.2','ConveyorLine.alp')]:
            _,model=load(base/task/'1'/name)
            main=by_name(child(model,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
            blocks=by_name(child(main,'EmbeddedObjects'),'EmbeddedObject')
            self.assertEqual(param(blocks['source1'],'arrivalType'),'self.MANUAL')
            self.assertEqual(param(blocks['source1'],'rate'),'')
            variation=children(child(model,'Experiments'),'ParamVariationExperiment')
            self.assertEqual([field(v,'Name') for v in variation],['Capacity'])
            self.assertEqual(field(child(variation[0],'ModelTimeProperties'),'FinalTime'),'900')
            self.assertIn('throughputData.add',field(variation[0],'AfterSimulationRunCode'))
            plot=variation[0].getElementsByTagName('Plot')[0]
            self.assertEqual(field(plot,'AutoUpdate'),'false')
            self.assertIn('instanceof com.anylogic.engine.ExperimentSimulation',field(main,'StartupCode'))
            if task=='5.1':
                self.assertNotIn('stockPallets',blocks);self.assertNotIn('fitSheet',blocks)
            else:
                self.assertEqual(param(blocks['loadingTravel'],'targetPositionOnConveyor'),'sheetJoin')
                self.assertEqual(param(blocks['sheetTravel'],'targetPositionOnConveyor'),'assemblyJoin')
                self.assertIn('stockPallets',blocks)
            for link in children(child(main,'Connectors'),'Connector'):
                points=[(float(field(p,'X')),float(field(p,'Y'))) for p in children(child(link,'Points'),'Point')]
                for a,b in zip(points,points[1:]):
                    self.assertTrue(a[0]==b[0] or a[1]==b[1],(task,field(link,'Name'),a,b))
            # Input of the perpendicular part cannot pass through the manual Source.
            self.assertGreater(float(field(blocks['source1'],'X')),float(field(blocks['fitPart'],'X'))+50)
