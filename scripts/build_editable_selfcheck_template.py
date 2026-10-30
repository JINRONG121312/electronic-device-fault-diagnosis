from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt

OUT = Path("output/word/自查报告模板_可编辑版_一级二级仅保留标题.docx")
FONT = "宋体"


def set_run(run, size=12, bold=False, font=FONT):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font)
    return run


def yellow_blank(paragraph, chars=8):
    # Non-breaking spaces keep highlighted fill visible at paragraph ends.
    run = set_run(paragraph.add_run("\u00a0" * chars))
    run.font.highlight_color = 7
    return run


def add_text(doc, text="", size=12, bold=False, align=None, before=0, after=0,
             line=1.5, indent=0, keep=False):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = line
    p.paragraph_format.first_line_indent = Cm(indent) if indent else None
    p.paragraph_format.keep_with_next = keep
    set_run(p.add_run(text), size=size, bold=bold)
    return p


def add_mixed(doc, parts, size=12, align=None, indent=0, line=1.5, after=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.first_line_indent = Cm(indent) if indent else None
    p.paragraph_format.line_spacing = line
    p.paragraph_format.space_after = Pt(after)
    for kind, value in parts:
        if kind == "text":
            set_run(p.add_run(value), size=size)
        else:
            yellow_blank(p, value)
    return p


def configure(section, landscape=False):
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Mm(297), Mm(210)
        section.top_margin = section.bottom_margin = Mm(15)
        section.left_margin = section.right_margin = Mm(15)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.top_margin = section.bottom_margin = Mm(20)
        section.left_margin = section.right_margin = Mm(28)
    section.header_distance = Mm(8)
    section.footer_distance = Mm(8)


def new_page(doc, landscape=False):
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    configure(section, landscape)
    return section


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell(cell, text, size=8, bold=False, yellow=False):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1
    set_run(p.add_run(text), size=size, bold=bold)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if yellow:
        shade(cell, "FFFF00")


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_page_number(section, number):
    section.footer.is_linked_to_previous = False
    p = section.footer.paragraphs[0]
    for child in list(p._p):
        p._p.remove(child)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(str(number)), size=9)


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    configure(doc.sections[0], False)

    # Page 1: cover
    add_text(doc, "附件2", size=14, after=28)
    add_text(doc, "XX设备账物一致性自主可控自查报告", size=22, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, after=62)
    for label in ("编制：", "校对：", "审核："):
        p = add_text(doc, label, size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
        yellow_blank(p, 12)
    p = add_text(doc, "系统会签：", size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    yellow_blank(p, 16)
    set_run(p.add_run(" 系统（副）主任设计师"), size=14)
    p = add_text(doc, "质签：", size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    yellow_blank(p, 16)
    set_run(p.add_run(" 提交单位质量部门"), size=14)
    p = add_text(doc, "批准：", size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=55)
    yellow_blank(p, 12)
    add_text(doc, "设备技术责任单位/供货单位", size=14,
             align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
    add_text(doc, "2025年6月", size=14, align=WD_ALIGN_PARAGRAPH.CENTER)

    # Page 2
    sec = new_page(doc, False); set_page_number(sec, 2)
    add_text(doc, "一、概述", size=14, bold=True, keep=True, after=4)
    add_mixed(doc, [("blank", 5), ("text", "设备为研制/改进/设计/选用（四选一）设备，技术责任单位为"),
                    ("blank", 8), ("text", "和供货单位为"), ("blank", 8), ("text", "。")],
              size=12, indent=0.8)
    add_mixed(doc, [("blank", 5), ("text", "设备根据《关于加强武器装备使用国产电子元器件管理的意见》、"),
                    ("text", "《"), ("blank", 8), ("text", "项目电子元器件“双清单”动态管控要求》、"),
                    ("text", "《"), ("blank", 8), ("text", "项目自主可控设计要求》、JZ信〔2023〕149号《关于组织开展"),
                    ("blank", 12), ("text", "使用进口数字信号处理器清查的通知》等要求，通过加强顶层设计、加大科研攻关、落实应用验证、加强审查把控等措施，严格执行核心高端电子元器件100%自主可控、进口电子元器件实行清单制特批的刚性要求。")],
              size=12, indent=0.8)
    add_text(doc, "二、电子元器件“双清单”审查情况", size=14, bold=True, keep=True, after=4)
    add_text(doc, "情形一：设备前期已随型号研总开展过双清单审查", size=12, bold=True, indent=0.8)
    add_mixed(doc, [("text", "2023年，随着型号研制总要求阶段电子元器件“双清单”开展了审查，国产电子元器件"),
                    ("blank", 6), ("text", "条、进口电子元器件"), ("blank", 6),
                    ("text", "条，国产化率为"), ("blank", 5), ("text", "%。由于"),
                    ("blank", 10), ("text", "（描述“双清单”为什么发生变化，要求理由合情合理）等原因，设备电子元器件“双清单”发生了变化，根据"),
                    ("blank", 10), ("text", "总师办〔2024〕178号《"), ("blank", 10),
                    ("text", "电子元器件“双清单”动态管控要求》要求，相对于研总阶段“双清单”，对不再使用部分进行了删除，删除"),
                    ("blank", 5), ("text", "条；对新增部分委托第三方服务机构进行了审查，新增"),
                    ("blank", 5), ("text", "条，审查情况详见第三方审查报告。最终设备电子元器件“双清单”为：国产电子元器件"),
                    ("blank", 6), ("text", "条，进口电子元器件"), ("blank", 6),
                    ("text", "条，电子元器件国产规格比为"), ("blank", 5), ("text", "%，国产数量比为"),
                    ("blank", 5), ("text", "%，满足技术规格书“规格国产化率"), ("blank", 5),
                    ("text", "%、数量国产化率"), ("blank", 5), ("text", "%”的要求。")],
              size=11.5, indent=0.8, line=1.35)

    # Page 3
    sec = new_page(doc, False); set_page_number(sec, 3)
    add_text(doc, "情形二：设备前期未随型号研总开展过双清单审查", size=12, bold=True, indent=0.8)
    add_mixed(doc, [("text", "2023年，由于"), ("blank", 12),
                    ("text", "（描述“双清单”为什么未随研总开展审查，要求理由合情合理）等原因，未随着型号研制总要求阶段电子元器件“双清单”开展审查。根据"),
                    ("blank", 10), ("text", "总师办〔2024〕178号《"), ("blank", 10),
                    ("text", "电子元器件“双清单”动态管控要求》要求，委托第三方服务机构进行了审查，审查情况详见第三方审查报告。最终设备电子元器件“双清单”为：国产电子元器件"),
                    ("blank", 6), ("text", "条，进口电子元器件"), ("blank", 6),
                    ("text", "条，电子元器件国产规格为"), ("blank", 5), ("text", "%、国产数量比为"),
                    ("blank", 5), ("text", "%，满足技术规格书“规格国产化率"), ("blank", 5),
                    ("text", "%、数量国产化率"), ("blank", 5), ("text", "%”的要求。")],
              size=11.5, indent=0.8, line=1.35)
    add_text(doc, "三、电子元器件“双清单”与实物一致性自查情况", size=14, bold=True, keep=True)
    add_mixed(doc, [("text", "设备出所检验前，根据设备审定后整机电子元器件“双清单”和出所检验验收细则的要求，"),
                    ("blank", 5), ("text", "年"), ("blank", 3), ("text", "月"), ("blank", 3),
                    ("text", "日，采用查阅资料、比对图纸和核查实物（如实物可查）等方式，针对实物与“双清单”一致性进行了检查，检查情况详见检查记录（模板详见附件5），检查结果未发现差异项。")],
              size=11.5, indent=0.8, line=1.35)
    add_text(doc, "四、“伪、空、包”电子元器件自查情况", size=14, bold=True, keep=True)
    add_mixed(doc, [("text", "按照"), ("blank", 10), ("text", "总师办〔2024〕178号《"),
                    ("blank", 10), ("text", "电子元器件“双清单”动态管控要求》要求，根据设备审定后电子元器件“双清单”、最新“伪、空、包”产品清单（"),
                    ("blank", 5), ("text", "版）（要求是截止报告编制时最新版“伪、空、包”产品清单）和JZ信〔2023〕149号《关于组织开展"),
                    ("blank", 12), ("text", "使用进口数字信号处理器清查的通知》，识别了伪国产化产品"),
                    ("blank", 5), ("text", "条、空心国产化产品"), ("blank", 5),
                    ("text", "条、包装国产化产品"), ("blank", 5), ("text", "条，并逐条制定了国产化整改方案，明确替代产品型号、厂家、替换时机，并经过技术线组织行业专家进行评审，其中“伪、空、包”产品已纳入进口电子元器件清单进行管控，具体情况详见“伪、空、包”问题整治工作台账。")],
              size=11.2, indent=0.8, line=1.3)

    # Page 4
    sec = new_page(doc, False); set_page_number(sec, 4)
    add_text(doc, "五、存在安全风险的DSP元器件和苏州雄立公司产品自查情况", size=14, bold=True, keep=True)
    add_mixed(doc, [("text", "根据JZ信〔2023〕149号《关于组织开展"), ("blank", 12),
                    ("text", "使用进口数字信号处理器清查的通知》要求，针对11款被探明存在隐藏指令的风险DSP元器件使用情况进行自查，本设备未发现使用该范围的元器件。（特别说明：若发现有使用此范围的元器件，不允许放行，必须进行整改。）")],
              size=12, indent=0.8)
    add_text(doc, "根据《关于通报苏州雄立科技有限公司科研项目造假情况事》（军装计〔2025〕616号）、《关于梳理苏州雄立科技有限公司产品情况的函》（海装专项函〔2025〕456号）要求，开展自查，设备未发现使用该范围的元器件。",
             size=12, indent=0.8)
    add_text(doc, "附件1  第三方“双清单”审查评估报告（如有）", size=12, before=18, after=5)
    add_text(doc, "附件2  “双清单”变化情况表（如有）", size=12, after=5)
    add_text(doc, "附件3  XX设备实物一致性检查记录表", size=12, after=5)
    add_text(doc, "附件4  “伪、空、包”问题整治工作台账（如有）", size=12, after=5)
    add_text(doc, "附件5  “伪、空、包”问题整治工作台账评审意见（如有）", size=12)

    # Page 5
    sec = new_page(doc, True); set_page_number(sec, 5)
    add_text(doc, "附件3  “双清单”变化情况表模板", size=13, bold=True, after=4)
    add_text(doc, "表1  “双清单”变化情况表", size=15, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    headers = ["一级系统名称","二级系统名称","设备名称","设备研制单位","是否完成“双清单”更新","是否完成第三方审查评估","原国产条目数","原进口条目数","原国产数量","原进口数量","现国产条目数","现进口条目数","现国产数量","现进口数量","原国产化比例","现国产化比例"]
    table = doc.add_table(rows=3, cols=16)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        set_cell(table.cell(0, i), h, size=6.5, bold=True)
        set_cell(table.cell(1, i), str(i + 1), size=7)
        set_cell(table.cell(2, i), "", yellow=True)
    set_repeat_table_header(table.rows[0])
    notes = [
        "填表说明：",
        "1  一级系统名称：",
        "2  二级系统名称：",
        "3  设备名称：元器件所属单机设备的名称；",
        "4  设备研制单位：元器件所属单机设备的承研承制单位名称；",
        "5  是否完成“双清单”更新：是否依据《XXXXX电子元器件“双清单”动态管控要求》完成“双清单”更新编制；",
        "6  是否完成第三方审查评估：是否依据《XXXXX电子元器件“双清单”动态管控要求》完成“双清单”第三方审查评估；",
        "7  原国产条目数：研制总要求上报阶段设备选用国产电子元器件条目数；",
        "8  原进口条目数：研制总要求上报阶段设备选用进口电子元器件条目数；",
        "9  原国产数量：研制总要求上报阶段设备选用国产电子元器件总数量；",
        "10  原进口数量：研制总要求上报阶段设备选用进口电子元器件总数量；",
        "11  现国产条目数：“双清单”更新后设备选用国产电子元器件条目数；",
        "12  现进口条目数：“双清单”更新后设备选用进口电子元器件条目数；",
        "13  现国产数量：“双清单”更新后设备选用国产电子元器件总数量；",
        "14  现进口数量：“双清单”更新后设备选用进口电子元器件总数量；",
        "15  原国产化比例：研制总要求上报阶段设备国产化比例；",
        "16  现国产化比例：“双清单”更新后设备国产化比例。",
    ]
    for i, t in enumerate(notes):
        add_text(doc, t, size=8.5, bold=(i == 0), line=1.0, after=0)

    # Page 6
    sec = new_page(doc, True); set_page_number(sec, 6)
    add_text(doc, "附件4  “伪、空、包”问题整治工作台账", size=13, bold=True, after=4)
    add_text(doc, "表2  “伪、空、包”问题整治工作台账", size=15, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    headers = ["一级系统名称","二级系统名称","设备名称","设备研制单位","元器件名称","型号规格","生产厂家","质量等级","封装形式","单机使用数量","“伪、空、包”类型","替代型号","替代厂家","替代方式","计划完成时间","负责人/电话"]
    table = doc.add_table(rows=3, cols=16)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        set_cell(table.cell(0, i), h, size=6.5, bold=True)
        set_cell(table.cell(1, i), str(i + 1), size=7)
        set_cell(table.cell(2, i), "", yellow=True)
    notes = [
        "填表说明：",
        "1  一级系统名称：",
        "2  二级系统名称：",
        "3  设备名称：元器件所属单机设备的名称；",
        "4  设备研制单位：元器件所属单机设备的承研承制单位名称；",
        "5  元器件名称：元器件供货时的名称，填写元器件中文全称；",
        "6  型号规格：元器件完整型号规格；",
        "7  生产厂家：元器件生产厂商名称；",
        "8  质量等级：器件生产控制质量等级，如MIL-PRF-38535 Q级、MIL-PRF-38534 H级、工业级、商业级等；",
        "9  封装形式：元器件为标准封装的填写封装形式代码，如CERDIP8、TSOP48、BGA144等；非标准封装填写外形尺寸，如10×10×2.2，单位默认为mm；",
        "10  单机使用数量：元器件在单机设备中的使用数量",
        "11  “伪、空、包”类型：伪国产化、包装国产化、空心国产化",
        "12  替代型号：替代方式为原位替代或功能替代时，必填；",
        "13  替代厂家：替代方式为原位替代或功能替代时，必填；",
        "14  替代方式：原位替代、功能替代、优化设计三选一；",
        "15  计划完成时间：计划完成替代验证的时间，具体到年月；",
        "16  负责人/电话：必须是设备研制单位相关负责人，禁止填报外包/外协等单位人员。",
    ]
    for i, t in enumerate(notes):
        add_text(doc, t, size=8.3, bold=(i == 0), line=1.0, after=0)

    # Page 7
    sec = new_page(doc, True); set_page_number(sec, 7)
    add_text(doc, "附件5  XX设备实物一致性检查记录表模板", size=13, bold=True, after=4)
    add_text(doc, "表3  XX设备实物一致性检查记录表", size=15, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    table = doc.add_table(rows=5, cols=10)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    merged = table.cell(0, 0).merge(table.cell(0, 7))
    set_cell(merged, "电子元器件“双清单”信息", size=9, bold=True)
    merged = table.cell(0, 8).merge(table.cell(0, 9))
    set_cell(merged, "检查情况", size=9, bold=True)
    heads = ["序号","设备名称","元器件名称","型号规格","单机使用数量","生产厂商","质量等级","封装形式","核对资料/实物","检查结论"]
    for i, h in enumerate(heads):
        set_cell(table.cell(1, i), h, size=8, bold=True)
    samples = [
        ["示例1","XXX","精密低压差基准源","CX192SN","2","XXX公司","军用级","SOIC-8","（图号）XXX图纸","产品及数量一致"],
        ["示例2","XXX","隔离式RS-485/RS-422收发器","JM3096W","4","XXX公司","工业级","SOIC16","实物","产品及数量一致"],
    ]
    for r, vals in enumerate(samples, 2):
        for c, value in enumerate(vals):
            set_cell(table.cell(r, c), value, size=8)
    for c in range(10):
        set_cell(table.cell(4, c), "", yellow=True)
    p = add_text(doc, "检查单位：", size=13, before=10, after=12)
    yellow_blank(p, 18)
    p = add_text(doc, "检查人：", size=13)
    yellow_blank(p, 18)

    # Page 8
    sec = new_page(doc, False); set_page_number(sec, 1)
    add_text(doc, "附件3", size=14, after=22)
    add_text(doc, "XXX设备电子元器件“双清单”账物一致性承诺书", size=18, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, after=38)
    add_mixed(doc, [("text", "我单位依据相关法规要求，编制了"), ("blank", 10),
                    ("text", "（设备/系统名称）国产和进口电子元器件清单（以下称“双清单”），其中国产"),
                    ("blank", 5), ("text", "项，进口"), ("blank", 5),
                    ("text", "项，报送信息全面详实，不存在漏报、瞒报、误报情况，经我单位自查，清单与实物一致，“双清单”中的国产电子元器件无伪国产化或包装国产化问题。")],
              size=13, indent=0.8, line=1.8)
    add_text(doc, "特此承诺。", size=13, before=25, after=42)
    p = add_text(doc, "", size=13, align=WD_ALIGN_PARAGRAPH.RIGHT, after=18)
    yellow_blank(p, 12)
    set_run(p.add_run("（设备/系统名称承制单位名称并加盖公章）"), size=13)
    p = add_text(doc, "", size=13, align=WD_ALIGN_PARAGRAPH.RIGHT)
    yellow_blank(p, 6); set_run(p.add_run("年"), size=13)
    yellow_blank(p, 4); set_run(p.add_run("月"), size=13)
    yellow_blank(p, 4); set_run(p.add_run("日"), size=13)

    doc.core_properties.title = "自查报告模板"
    doc.core_properties.subject = "PDF转Word可编辑模板；原打码处以黄色留空表示"
    doc.save(OUT)
    print(OUT.resolve())


if __name__ == "__main__":
    build()
