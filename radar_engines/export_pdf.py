#!/usr/bin/env python
"""
PDF导出脚本
"""
import json
import sys
from datetime import datetime
from pathlib import Path

BETTAFISH_ROOT = Path(__file__).resolve().parent
IR_OUTPUT_DIR = BETTAFISH_ROOT / "outputs" / "final_reports" / "ir"
PDF_OUTPUT_DIR = BETTAFISH_ROOT / "outputs" / "final_reports" / "pdf"

if str(BETTAFISH_ROOT) not in sys.path:
    sys.path.insert(0, str(BETTAFISH_ROOT))


def find_latest_ir_report():
    """查找最新的报告 IR 文件"""
    if not IR_OUTPUT_DIR.exists():
        return None

    candidates = sorted(
        IR_OUTPUT_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def export_pdf(ir_file_path):
    """导出PDF"""
    try:
        ir_path = Path(ir_file_path)

        # 读取IR文件
        print(f"正在读取报告文件: {ir_path}")
        with ir_path.open('r', encoding='utf-8') as f:
            document_ir = json.load(f)

        # 导入PDF渲染器
        from ReportEngine.renderers.pdf_renderer import PDFRenderer

        # 创建PDF渲染器
        print("正在初始化PDF渲染器...")
        renderer = PDFRenderer()

        # 生成PDF
        print("正在生成PDF...")
        pdf_bytes = renderer.render_to_bytes(document_ir, optimize_layout=True)

        # 确定输出文件名
        topic = document_ir.get('metadata', {}).get('topic', 'report')
        PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        pdf_filename = f"report_{topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        output_path = PDF_OUTPUT_DIR / pdf_filename

        # 保存PDF文件
        print(f"正在保存PDF到: {output_path}")
        with output_path.open('wb') as f:
            f.write(pdf_bytes)

        print("✅ PDF导出成功！")
        print(f"文件位置: {output_path}")
        print(f"文件大小: {len(pdf_bytes) / 1024 / 1024:.2f} MB")

        return str(output_path)

    except Exception as e:
        print(f"❌ PDF导出失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    latest_report = find_latest_ir_report()

    if latest_report is not None:
        print("=" * 50)
        print("开始导出PDF")
        print("=" * 50)
        result = export_pdf(latest_report)
        if result:
            print(f"\n📄 PDF文件已生成: {result}")
    else:
        print(f"❌ 在 {IR_OUTPUT_DIR} 下未找到报告 IR 文件")
