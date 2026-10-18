# SPDX-License-Identifier: GPL-3.0-only
"""Regression tests for v0.6.9.5: never silently lose engineering geometry."""
import math
import pytest
from pycad2d.geometry import m_translate, m_rotate, m_scale
from pycad2d.model import Document, Block, Line, Solid3D
from pycad2d import io_utils as IO
from pycad2d import i18n


def test_block_mutation_undo_redo():
    doc = Document()
    doc.blocks['B'] = Block(name='B', entities=[Line(x1=0, y1=0, x2=2, y2=0)])
    doc.push_undo()
    doc.blocks['B'].entities.append(Line(x1=3, y1=0, x2=4, y2=0))
    assert len(doc.blocks['B'].entities) == 2
    assert doc.undo()
    assert len(doc.blocks['B'].entities) == 1
    assert doc.redo()
    assert len(doc.blocks['B'].entities) == 2


def test_brep_xy_transform_preserves_cylinder(tmp_path):
    cq=pytest.importorskip('cadquery')
    original=cq.Workplane('XY').cylinder(5,2).val()
    solid = Solid3D(vertices=[(0,0,0),(1,0,0),(0,1,0)], faces=[[0,1,2]],
        shape='STEP', brep_b64=IO._shape_to_brep_b64(original))
    out = solid.transformed(m_translate(4,8)).transformed(m_rotate((0,0),30)).transformed(m_scale((0,0),2))
    result = IO._shape_from_brep_b64(out.brep_b64)
    assert result.Volume()==pytest.approx(original.Volume()*8, rel=1e-5)
    assert len([f for f in result.Faces() if f.geomType()=='CYLINDER'])==1
    assert out.vertices[0] == pytest.approx((-1.07179677, 17.85640646, 0),abs=1e-5)


def test_brep_nonuniform_refuses_data_loss():
    cq=pytest.importorskip('cadquery')
    solid=Solid3D(vertices=[(0,0,0)],brep_b64=IO._shape_to_brep_b64(cq.Workplane().sphere(2).val()))
    with pytest.raises(ValueError, match='BREP'):
        solid.transformed(m_scale((0,0),2,3))


def test_gltf_units_roundtrip(tmp_path):
    trimesh=pytest.importorskip('trimesh')
    # 1 metre cube should import as 1000 millimetres.
    src=tmp_path/'metre.glb'
    trimesh.creation.box(extents=[1,1,1]).export(src)
    doc=Document()
    imported=IO.import_3d(str(src),doc)
    bbox=imported[0].bbox3d()
    assert bbox[3]-bbox[0] == pytest.approx(1000)
    doc.entities=imported
    exported=tmp_path/'roundtrip.glb'
    IO.export_gltf(str(exported),doc)
    result=trimesh.load(exported,force='mesh')
    assert result.extents[0] == pytest.approx(1)


def test_gltf_non_mm_document(tmp_path):
    trimesh=pytest.importorskip('trimesh')
    src=tmp_path/'metre.glb'
    trimesh.creation.box(extents=[1,1,1]).export(src)
    doc=Document()
    doc.vars['INSUNITS']=6 # m
    imported=IO.import_3d(str(src),doc)
    assert imported[0].bbox3d()[3]-imported[0].bbox3d()[0] == pytest.approx(1)


def test_language_catalog():
    i18n.set_language('en')
    assert i18n.tr('檔案(&F)') == 'File (&F)'
    assert i18n.tr('新建(&N)') == 'New (&N)'
    assert i18n.tr('常用') == 'Home'
    i18n.set_language('zh_TW')
    assert i18n.tr('常用') == '常用'


def test_undo_mutated_entity_inside_block():
    doc=Document()
    doc.blocks['mutated']=Block(name='mutated',entities=[Line(x1=1,y1=1,x2=5,y2=5)])
    doc.push_undo()
    doc.blocks['mutated'].entities[0].x1=100
    assert doc.undo()
    assert doc.blocks['mutated'].entities[0].x1==1


def test_simplification_preserves_closed_display():
    trimesh=pytest.importorskip('trimesh')
    mesh=trimesh.creation.icosphere(subdivisions=5,radius=5)
    source=Solid3D(vertices=mesh.vertices.tolist(),faces=mesh.faces.tolist())
    vv,ff,_=source.display_mesh(2500)
    assert trimesh.Trimesh(vertices=vv,faces=ff,process=False).is_watertight
