# SPDX-License-Identifier: GPL-3.0-only
"""Traditional Chinese / English UI text catalog.

Labels use their Traditional Chinese source as stable lookup keys; CAD command
identifiers and saved drawing data never change with the display language.
Untranslated legacy command prompts are deliberately shown in their source
language rather than guessed by machine translation.
"""
import re

EN = {
    '檔案':'File','編輯':'Edit','檢視':'View','插入':'Insert','格式':'Format',
    '工具':'Tools','繪製':'Draw','標註':'Dimension','修改':'Modify','說明':'Help',
    '語言':'Language','繁體中文':'Traditional Chinese','英文':'English',
    '新建':'New','新圖面':'New drawing','開啟':'Open','儲存':'Save','另存新檔':'Save As',
    '關閉':'Close','結束':'Exit','退回':'Undo','重做':'Redo','剪下':'Cut','複製':'Copy',
    '貼上':'Paste','全部選取':'Select All','刪除':'Delete','重生':'Regenerate',
    '縮放實際範圍':'Zoom Extents','縮放視窗':'Window Zoom','上一個視圖':'Previous View',
    '上視圖':'Top View','下視圖':'Bottom View','前視圖':'Front View','右視圖':'Right View',
    '東南等角視圖':'SE Isometric','西南等角視圖':'SW Isometric',
    '東北等角視圖':'NE Isometric','西北等角視圖':'NW Isometric',
    '圖塊':'Block','建立圖塊':'Create Block','圖層':'Layer','顏色':'Color',
    '線型比例':'Linetype Scale','文字高度':'Text Height','標註比例':'Dimension Scale',
    '性質':'Properties','製圖設定':'Drafting Settings','圖面單位':'Drawing Units',
    '距離':'Distance','面積':'Area','點座標':'Point Coordinates','列示':'List',
    '清除':'Purge','刪除重複物件':'Remove Duplicates',
    '指令一覽':'Command Reference','功能區':'Ribbon','指令行':'Command Line',
    '快速存取':'Quick Access','模型':'Model','上視':'Top','下視':'Bottom',
    '前視':'Front','後視':'Back','左視':'Left','右視':'Right',
    '東南等角':'SE Isometric','西南等角':'SW Isometric','東北等角':'NE Isometric',
    '西北等角':'NW Isometric','工作區':'Workspace','製圖與註解':'Drafting & Annotation',
    '3D 建模':'3D Modeling','常用':'Home','註解':'Annotate','輸出':'Output',
    '實體':'Solid','曲面':'Surface','網面':'Mesh','視覺化':'Visualize',
    '線':'Line','聚合線':'Polyline','圓':'Circle','弧':'Arc','矩形':'Rectangle',
    '多邊形':'Polygon','橢圓':'Ellipse','填充線':'Hatch','雲形線':'Spline',
    '建構線':'Construction Line','點':'Point','射線':'Ray','修訂雲形':'Revision Cloud',
    '移動':'Move','拉伸':'Stretch','旋轉':'Rotate','鏡射':'Mirror','比例':'Scale',
    '修剪':'Trim','延伸':'Extend','偏移':'Offset','圓角':'Fillet','倒角':'Chamfer',
    '陣列':'Array','分解':'Explode','接合':'Join','切斷':'Break','等分':'Divide',
    '線性':'Linear','對齊':'Aligned','角度':'Angle','半徑':'Radius','直徑':'Diameter',
    '引線':'Leader','文字':'Text','多行文字':'Multiline Text','單行文字':'Single-line Text',
    '編輯文字':'Edit Text','圖層\n性質':'Layer\nProperties','設為目前':'Make Current',
    '隔離':'Isolate','取消隔離':'Unisolate','凍結':'Freeze','鎖護':'Lock',
    '全部打開':'Turn All On','全部解凍':'Thaw All','全部解鎖':'Unlock All',
    '建立':'Create','複製\n性質':'Match\nProperties','公用程式':'Utilities',
    '選取類似':'Select Similar','剪貼簿':'Clipboard','匯入':'Import','匯出':'Export',
    '多重引線':'Multileader','填充線與標記':'Hatches & Marks','導覽':'Navigate',
    '實際範圍':'Extents','視窗':'Window','上一個':'Previous','標準視圖':'Standard Views',
    '選項板':'Palettes','製圖輔助':'Drafting Aids','方塊':'Box','擠出':'Extrude',
    '掃掠':'Sweep','混成':'Loft','圓柱體':'Cylinder','圓錐體':'Cone','球體':'Sphere',
    '楔體':'Wedge','金字塔':'Pyramid','圓環':'Torus','布林':'Boolean',
    '聯集':'Union','差集':'Subtract','交集':'Intersect','切割':'Slice',
    '3D 修改':'3D Modify','3D 移動':'3D Move','精準定位':'Precision Placement',
    '3D 旋轉':'3D Rotate','3D 比例':'3D Scale','3D 鏡射':'3D Mirror',
    '邊圓角':'Edge Fillet','邊倒角':'Edge Chamfer','視圖 / 導覽':'View / Navigate',
    '3D\n軌道':'3D\nOrbit','四視埠':'Four Viewports','動態 UCS':'Dynamic UCS',
    '視覺型式':'Visual Styles','著色\n含邊線':'Shaded\nwith Edges',
    '3D 線架構':'3D Wireframe','2D 線架構':'2D Wireframe','概念':'Conceptual',
    '3D 資料交換':'3D Exchange','匯入\n3D':'Import\n3D','縮放':'Zoom',
    '基本實體':'Primitives','實體編輯':'Solid Editing','建立曲面 / 實體特徵':'Surface / Solid Features',
    '網格資料':'Mesh Data','匯入網格':'Import Mesh','著色含邊線':'Shaded with Edges',
    '3D 軌道':'3D Orbit','出圖':'Plot','匯入 3D 模型':'Import 3D Model',
    '選取顏色':'Choose Color','目前顏色':'Current Color','來源格式':'Source Format',
    '指令':'Command','別名':'Alias','取消':'Cancel','確定':'OK',
    '顯示':'Display','設定':'Settings','無單位':'Unitless','毫米':'Millimeters',
    '公分':'Centimeters','公尺':'Meters','英吋':'Inches','英呎':'Feet',
    '中心點':'Center','端點':'Endpoint','中點':'Midpoint','交點':'Intersection',
    '距離:':'Distance:','角度:':'Angle:','極座標:':'Polar:',
}

LANGUAGES = ('zh_TW','en')
_current = 'zh_TW'

def set_language(code):
    global _current
    _current = code if code in LANGUAGES else 'zh_TW'

def language():
    return _current

def tr(text):
    if _current != 'en' or not text:
        return text
    original = str(text)
    if original in EN:
        return EN[original]
    if "\n" in original:
        first, rest = original.split("\n", 1)
        if first in EN:
            return EN[first] + "\n" + rest
    # Preserve Qt mnemonic (e.g. 新建(&N)); avoid altering shortcut tokens.
    text = re.sub(r'\(&([A-Za-z])\)', '', original)
    suffix = '...' if text.endswith('...') else ''
    if suffix:
        text = text[:-3]
    if text in EN:
        shortcut_match = re.search(r'\(&([A-Za-z])\)', original)
        return EN[text] + (f' (&{shortcut_match.group(1)})' if shortcut_match else '') + suffix
    # Format-specific actions, eg. 匯出 STEP 3D...
    for lead, translation in (('匯出 ','Export '),('匯入 ','Import ')):
        if text.startswith(lead):
            return translation + tr(text[len(lead):])
    return original
