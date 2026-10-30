"""校园二手交易系统 UI 原型。使用 ReportLab 矢量画布绘制，再导出 PNG。"""
from pathlib import Path
import subprocess
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parent
TMP = ROOT / "_render_tmp"
TMP.mkdir(exist_ok=True)
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
pdfmetrics.registerFont(TTFont("Hei", FONT, subfontIndex=0))

W, H = 1440, 900
BG = "#F4F7FB"
WHITE = "#FFFFFF"
NAVY = "#172B4D"
BLUE = "#246BCE"
BLUE_LIGHT = "#EAF2FF"
MUTED = "#68778F"
BORDER = "#DDE5EF"
GREEN = "#1D8E65"
GREEN_LIGHT = "#E6F5EF"
ORANGE = "#D98025"
ORANGE_LIGHT = "#FFF1E1"
RED = "#C95454"
RED_LIGHT = "#FFF0F0"


def col(v):
    return HexColor(v)


def rect(c, x, y, w, h, fill=WHITE, stroke=None, r=0, sw=1):
    c.setLineWidth(sw)
    c.setFillColor(col(fill))
    c.setStrokeColor(col(stroke or fill))
    c.roundRect(x, H-y-h, w, h, r, fill=1, stroke=bool(stroke))


def line(c, x1, y1, x2, y2, color=BORDER, width=1):
    c.setStrokeColor(col(color)); c.setLineWidth(width)
    c.line(x1, H-y1, x2, H-y2)


def txt(c, x, y, s, size=16, color=NAVY, align="left"):
    c.setFont("Hei", size); c.setFillColor(col(color))
    fn = {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align]
    fn(x, H-y-size, str(s))


def pill(c, x, y, s, bg=BLUE_LIGHT, color=BLUE, w=None):
    w = w or max(70, 18 + len(s)*13)
    rect(c, x, y, w, 30, bg, r=15)
    txt(c, x+w/2, y+5, s, 13, color, "center")
    return w


def btn(c, x, y, w, s, primary=True, h=42, danger=False):
    bg = RED if danger else (BLUE if primary else WHITE)
    fg = WHITE if primary or danger else BLUE
    rect(c, x, y, w, h, bg, BORDER if not primary and not danger else None, 9)
    txt(c, x+w/2, y+(h-18)/2-1, s, 15, fg, "center")


def inputbox(c, x, y, w, label, value="", h=44):
    txt(c, x, y-24, label, 14, MUTED)
    rect(c, x, y, w, h, WHITE, BORDER, 8)
    if value: txt(c, x+14, y+10, value, 15, NAVY)


def card(c, x, y, w, h, title=None):
    rect(c, x, y, w, h, WHITE, BORDER, 13)
    if title: txt(c, x+22, y+18, title, 19)


def shell(c, active, title, subtitle=""):
    rect(c, 0, 0, W, H, BG)
    rect(c, 0, 0, 226, H, NAVY)
    rect(c, 0, 0, 226, 76, "#10203D")
    txt(c, 28, 24, "校园集市", 24, WHITE)
    txt(c, 28, 55, "校内二手交易", 11, "#B8C8E0")
    nav = ["商品广场", "我的商品", "我的预约", "站内消息", "成交统计", "管理工作台"]
    for i, label in enumerate(nav):
        yy = 104+i*58
        if label == active: rect(c, 14, yy, 198, 43, "#2C4771", r=8)
        txt(c, 35, yy+10, label, 16, WHITE if label == active else "#BDCCE0")
    line(c, 20, 825, 205, 825, "#3D5475")
    txt(c, 34, 842, "饶同学  ·  学生账号", 13, "#C9D5E5")
    rect(c, 226, 0, W-226, 75, WHITE)
    txt(c, 264, 22, title, 24)
    txt(c, 264, 55, subtitle, 12, MUTED)
    txt(c, 1335, 28, "帮助  ·  退出", 13, MUTED, "right")


def section(c, x, y, title, small=""):
    txt(c, x, y, title, 21)
    if small: txt(c, x, y+31, small, 13, MUTED)


def table(c, x, y, widths, headers, rows, row_h=54):
    total=sum(widths)
    rect(c,x,y,total,45,"#F1F5FA",r=7)
    xx=x
    for w,head in zip(widths,headers):
        txt(c,xx+14,y+12,head,14,MUTED); xx+=w
    for i,row in enumerate(rows):
        yy=y+45+i*row_h
        if i%2: rect(c,x,yy,total,row_h,"#FAFCFF")
        xx=x
        for w,v in zip(widths,row):
            txt(c,xx+14,yy+16,v,14,NAVY); xx+=w
        line(c,x,yy+row_h,x+total,yy+row_h)


def product_visual(c, x, y, w, h, kind="电脑"):
    rect(c,x,y,w,h,"#DDE9FA",r=9)
    rect(c,x+20,y+20,w-40,h-40,"#C7DCF5",r=8)
    if kind=="电脑":
        rect(c,x+w*.25,y+h*.24,w*.50,h*.42,"#263D60",r=8)
        rect(c,x+w*.27,y+h*.27,w*.46,h*.35,"#6EA4D7",r=3)
        rect(c,x+w*.20,y+h*.67,w*.60,h*.06,"#4B6585",r=4)
    elif kind=="书籍":
        rect(c,x+w*.33,y+h*.18,w*.36,h*.64,"#E19B59",r=4)
        rect(c,x+w*.37,y+h*.22,w*.28,h*.56,"#F9E8CF",r=2)
        line(c,x+w*.44,y+h*.35,x+w*.60,y+h*.35,"#9B6D4B",4)
    else:
        rect(c,x+w*.28,y+h*.25,w*.44,h*.47,"#7EB7A4",r=25)
        rect(c,x+w*.34,y+h*.18,w*.32,h*.14,"#466F66",r=7)


def login(c):
    rect(c,0,0,W,H,"#EAF2FF")
    rect(c,0,0,690,H,"#173B73")
    rect(c,94,108,502,500,"#214D8D",r=25)
    txt(c,82,145,"校园集市",43,WHITE)
    txt(c,85,211,"让闲置找到下一个主人",27,"#D5E6FF")
    txt(c,85,275,"仅面向本校学生 · 线下见面交付",17,"#C3D9F8")
    for i,(n,t) in enumerate([("01","学校邮箱验证"),("02","发布与审核"),("03","预约后线下交付")]):
        rect(c,88,357+i*84,480,63,"#2E5D9B",r=10)
        txt(c,110,374+i*84,n,19,"#A9D1FF")
        txt(c,165,375+i*84,t,18,WHITE)
    card(c,783,145,565,605)
    txt(c,826,187,"欢迎使用校园集市",28)
    txt(c,826,233,"先用学校邮箱完成验证，再设置密码登录。",16,MUTED)
    pill(c,826,281,"学校邮箱注册",BLUE_LIGHT,BLUE,148)
    pill(c,984,281,"已有账号登录","#F2F5FA",MUTED,148)
    inputbox(c,826,356,478,"学校邮箱","student@学校域名")
    inputbox(c,826,449,322,"邮箱验证码","请输入 6 位验证码")
    btn(c,1160,449,144,"发送验证码",False,44)
    inputbox(c,826,542,478,"设置密码","至少 8 位字符")
    btn(c,826,648,478,"验证并继续",True,50)
    txt(c,826,718,"学校邮箱域名以学校正式配置为准",13,MUTED)


def browse(c):
    shell(c,"商品广场","商品广场","只展示已发布、当前可预约的商品")
    card(c,264,102,1138,126)
    inputbox(c,286,153,410,"关键词","搜索名称或描述")
    inputbox(c,716,153,205,"分类","全部分类  ▾")
    inputbox(c,941,153,205,"价格区间","不限  ▾")
    btn(c,1170,153,204,"筛选商品")
    txt(c,267,256,"为你推荐",22)
    txt(c,1370,261,"发布时间 ↓    价格 ↑ / ↓",14,MUTED,"right")
    goods=[("电脑","九成新轻薄笔记本","¥ 2,850","数码"),("书籍","软件工程教材套装","¥ 68","书籍"),("其他","桌面绿植与花盆","¥ 25","生活")]
    for i,(kind,title,price,cat) in enumerate(goods):
        x=264+i*384
        card(c,x,306,364,430)
        product_visual(c,x+16,322,332,235,kind)
        txt(c,x+22,578,title,19)
        txt(c,x+22,615,cat+"  ·  校内面交",13,MUTED)
        txt(c,x+22,658,price,23,ORANGE)
        btn(c,x+229,653,112,"查看详情",False)
    txt(c,267,773,"列表不包含待审核、已预约和已下架商品。",13,MUTED)


def detail(c):
    shell(c,"商品广场","商品详情","商品广场 / 数码 / 九成新轻薄笔记本")
    card(c,264,106,700,620)
    product_visual(c,284,126,660,404,"电脑")
    txt(c,290,552,"九成新轻薄笔记本",26)
    pill(c,781,556,"已发布",GREEN_LIGHT,GREEN,92)
    txt(c,290,600,"2024 年购入，日常学习使用，支持校内当面验机。",16,MUTED)
    txt(c,290,640,"分类：数码设备   发布：10月29日   卖家：陈同学",14,MUTED)
    card(c,987,106,415,392)
    txt(c,1013,141,"¥ 2,850",34,ORANGE)
    txt(c,1013,198,"当前状态：可预约",16,GREEN)
    line(c,1012,239,1375,239)
    txt(c,1013,260,"交付方式",15,MUTED)
    txt(c,1013,293,"双方预约成功后，校内线下沟通交付",16)
    btn(c,1013,357,363,"立即预约",True,49)
    txt(c,1013,423,"预约前不会展示卖家联系方式",13,MUTED)
    card(c,987,520,415,206,"交易提醒")
    txt(c,1013,576,"· 卖家须在 24 小时内处理预约",15,MUTED)
    txt(c,1013,608,"· 仅确认后双方可查看联系方式",15,MUTED)
    txt(c,1013,640,"· 线下收货后由买家确认完成",15,MUTED)
    btn(c,1013,670,125,"举报商品",False,36)


def seller_list(c):
    shell(c,"我的商品","我的商品","管理草稿、审核状态和已发布商品")
    btn(c,1245,105,157,"+ 发布商品")
    for i,(label,num) in enumerate([("全部商品","12"),("待审核","2"),("已发布","7"),("已预约","1")]):
        x=264+i*286
        card(c,x,161,269,105)
        txt(c,x+22,178,label,15,MUTED); txt(c,x+22,207,num,30)
    card(c,264,293,1138,477)
    txt(c,288,317,"商品列表",20)
    table(c,285,365,[350,165,145,170,260],
          ["商品","价格","状态","更新时间","可执行操作"],
          [["九成新轻薄笔记本","¥ 2,850","已预约","10-30 12:15","查看预约"],
           ["软件工程教材套装","¥ 68","已发布","10-29 09:40","编辑 / 下架"],
           ["收纳箱一组","¥ 30","待审核","10-28 21:04","撤回"],
           ["自行车头盔","¥ 55","审核驳回","10-27 17:22","查看原因 / 修改"],
           ["桌面绿植与花盆","¥ 25","草稿","10-26 19:10","继续编辑"]],66)
    txt(c,288,741,"已发布内容修改后重新审核；已预约商品不能直接修改或下架。",13,MUTED)


def seller_booking(c):
    shell(c,"我的预约","处理收到的预约","仅商品卖家可处理自己商品的预约")
    card(c,264,109,1138,170)
    pill(c,292,133,"待卖家确认",ORANGE_LIGHT,ORANGE,132)
    txt(c,292,174,"九成新轻薄笔记本",23)
    txt(c,292,214,"买家：饶同学    预约价：¥ 2,850    创建于：10月30日 12:15",15,MUTED)
    txt(c,1145,158,"剩余 18 小时",18,ORANGE)
    btn(c,1115,210,120,"确认预约",True,42)
    btn(c,1248,210,120,"拒绝预约",False,42)
    card(c,264,307,1138,305,"拒绝预约时需要填写原因")
    txt(c,293,372,"原因选项",15,MUTED)
    for i,s in enumerate(["无法联系","时间地点无法协调","商品情况变化","其他"]):
        x=292+i*250
        rect(c,x,412,222,48,WHITE,BORDER,9)
        txt(c,x+16,425,"○  "+s,15)
    inputbox(c,292,515,1066,"选择“其他”时填写说明","请输入具体情况")
    txt(c,292,585,"超过创建后 24 小时，旧页面的确认或拒绝提交会被拦截。",13,MUTED)
    card(c,264,637,1138,130)
    txt(c,292,660,"后续流程",18)
    txt(c,292,704,"确认后双方可查看联系方式；确认起 7 天内由买家线下收货并确认完成。",15,MUTED)


def buyer_booking(c):
    shell(c,"我的预约","预约详情","我的预约 / 九成新轻薄笔记本")
    card(c,264,106,1138,148)
    pill(c,291,133,"已确认",GREEN_LIGHT,GREEN,95)
    txt(c,291,175,"九成新轻薄笔记本",25)
    txt(c,291,216,"预约价 ¥ 2,850  ·  确认于 10月30日 13:00  ·  到期日 11月6日 13:00",15,MUTED)
    card(c,264,281,544,296,"线下交付")
    txt(c,291,342,"卖家联系方式",15,MUTED)
    txt(c,291,384,"138 **** 3021",26)
    txt(c,291,428,"仅在预约仍已确认、商品仍已预约时提供。",13,MUTED)
    btn(c,291,492,490,"我已收到商品，确认完成",True,51)
    card(c,830,281,572,296,"预约进度")
    for i,(time,event) in enumerate([("10-30 12:15","预约已提交"),("10-30 13:00","卖家确认预约"),("11-05 13:00","预计到期前 24 小时提醒")]):
        txt(c,860,345+i*62,time,14,MUTED); txt(c,1034,345+i*62,event,16)
    card(c,264,604,1138,166,"完成前请核对")
    txt(c,292,657,"点击完成时会再次显示“我已线下收到商品，此操作不可撤销”。",16)
    txt(c,292,695,"完成、取消、超时或违规终止后，服务端不再提供对方联系方式。",14,MUTED)


def inbox(c):
    shell(c,"站内消息","站内消息","业务变化和到期提醒集中在这里")
    card(c,264,111,1138,653)
    txt(c,291,141,"全部消息",21); pill(c,405,140,"未读 3",BLUE_LIGHT,BLUE,95)
    messages=[("预约已确认","卖家已确认“九成新轻薄笔记本”的预约。","10-30 13:00",BLUE_LIGHT),
              ("预约进度提醒","预约提交已满 12 小时，卖家尚未处理。","10-29 22:15",ORANGE_LIGHT),
              ("商品审核通过","“软件工程教材套装”已发布，现可被预约。","10-29 09:40",GREEN_LIGHT),
              ("举报处理结果","你提交的商品举报已处理，可查看处理结论。","10-28 18:26","#F3F1FF"),
              ("预约已结束","一笔预约因到期失效，商品已恢复发布。","10-27 08:50","#F1F5FA")]
    for i,(title,body,when,bg) in enumerate(messages):
        yy=202+i*100
        rect(c,291,yy,1083,80,"#FAFCFF" if i<3 else WHITE,BORDER,8)
        rect(c,306,yy+19,40,40,bg,r=20)
        txt(c,365,yy+14,title,17)
        txt(c,365,yy+43,body,14,MUTED)
        txt(c,1351,yy+29,when,13,MUTED,"right")
    txt(c,291,732,"状态提交后生成消息；生成失败可重试，重复任务不会产生第二条相同消息。",13,MUTED)


def report_form(c):
    shell(c,"商品广场","举报商品","仅已登录学生可举报已发布或已预约的商品")
    card(c,264,110,1138,644)
    txt(c,292,146,"举报对象",18)
    rect(c,292,190,1080,80,"#F5F8FC",r=9)
    txt(c,312,209,"九成新轻薄笔记本",18)
    txt(c,312,239,"商品编号：G-1029  ·  当前状态：已发布",13,MUTED)
    txt(c,292,298,"违规类别",15,MUTED)
    for i,s in enumerate(["商品信息不实","违禁商品","骚扰或欺诈","其他"]):
        x=292+i*257
        rect(c,x,334,235,46,WHITE,BORDER,9)
        txt(c,x+16,346,"○  "+s,15)
    txt(c,292,416,"情况说明",15,MUTED)
    rect(c,292,451,1080,105,WHITE,BORDER,9)
    txt(c,307,467,"请写明具体情况，便于管理员核查……",15,MUTED)
    txt(c,292,585,"证据图片（可选）",15,MUTED)
    rect(c,292,618,172,75,"#F8FAFD",BORDER,8)
    txt(c,378,640,"+ 上传图片",14,MUTED,"center")
    btn(c,1187,646,184,"提交举报",True,46)
    txt(c,292,719,"同一学生对同一商品存在待处理举报时，重复提交会返回原举报。",13,MUTED)


def admin_review(c):
    shell(c,"管理工作台","商品审核","待审核商品仅管理员可操作")
    card(c,264,108,1138,161)
    txt(c,290,135,"待审核  8",27)
    txt(c,290,185,"按提交时间排序；处理前重新读取商品当前状态。",14,MUTED)
    pill(c,1236,139,"管理员",BLUE_LIGHT,BLUE,110)
    card(c,264,295,1138,447)
    txt(c,290,321,"审核队列",20)
    table(c,286,367,[360,150,190,190,196],
          ["商品","卖家","价格","提交时间","操作"],
          [["软件工程教材套装","陈同学","¥ 68","10-30 10:20","查看 / 审核"],
           ["桌面显示器 27 寸","李同学","¥ 680","10-30 09:35","查看 / 审核"],
           ["骑行头盔","王同学","¥ 55","10-29 20:10","查看 / 审核"]],68)
    rect(c,287,653,1083,63,"#FFF7ED",r=9)
    txt(c,306,670,"驳回必须填写理由；商品被卖家撤回后，旧审核页提交应提示状态已变化。",15,ORANGE)


def admin_report(c):
    shell(c,"管理工作台","举报处理","先核对商品现态，再提交处理结论")
    card(c,264,108,1138,186)
    pill(c,291,134,"待处理",ORANGE_LIGHT,ORANGE,95)
    txt(c,291,178,"商品信息不实 · 九成新轻薄笔记本",22)
    txt(c,291,223,"举报人：饶同学   说明：商品描述与实物情况可能不符",15,MUTED)
    txt(c,291,260,"同商品另有 2 条待处理举报",14,BLUE)
    card(c,264,319,548,397,"处理前核对")
    txt(c,291,377,"商品当前状态",15,MUTED); pill(c,466,372,"已预约",BLUE_LIGHT,BLUE,89)
    txt(c,291,421,"有效预约",15,MUTED); txt(c,466,421,"1 条（待卖家确认）",15)
    txt(c,291,473,"确认违规时的操作",16)
    txt(c,291,512,"· 同一事务内下架商品、终止有效预约",14,MUTED)
    txt(c,291,544,"· 其他待处理举报合并结案并通知",14,MUTED)
    txt(c,291,576,"· 若已完成或已下架，拒绝违规下架",14,MUTED)
    card(c,836,319,566,397,"处理结论")
    inputbox(c,863,408,510,"结论理由","请填写事实与处理依据")
    btn(c,863,502,244,"驳回举报",False,49)
    btn(c,1121,502,254,"确认违规并下架",True,49,danger=True)
    txt(c,863,591,"状态竞争时以先成功提交者为准，",14,MUTED)
    txt(c,863,622,"后提交操作需重新读取现态。",14,MUTED)


def stats_log(c):
    shell(c,"管理工作台","统计与操作日志","成交统计仅计算已完成预约，金额按预约价格快照汇总")
    for i,(label,value) in enumerate([("本月成交笔数","28"),("本月成交额","¥ 12,430"),("待审商品","8"),("待处理举报","5")]):
        x=264+i*286
        card(c,x,108,269,118)
        txt(c,x+20,132,label,15,MUTED); txt(c,x+20,166,value,29,BLUE if i<2 else NAVY)
    card(c,264,251,1138,505)
    txt(c,290,281,"关键操作日志",21)
    inputbox(c,290,347,222,"操作类型","全部  ▾")
    inputbox(c,530,347,222,"操作者","输入账号编号")
    inputbox(c,770,347,222,"目标编号","输入商品/预约编号")
    inputbox(c,1010,347,211,"时间范围","起止日期  ▾")
    btn(c,1241,347,135,"查询",True,44)
    table(c,287,425,[190,160,190,180,180,186],
          ["时间","操作者","操作","目标","前 → 后","结果"],
          [["10-30 13:00","陈同学","确认预约","R-1029","待确认 → 已确认","成功"],
           ["10-30 12:15","饶同学","创建预约","G-1029","已发布 → 已预约","成功"],
           ["10-30 12:15","另一买家","创建预约","G-1029","已预约 → 已预约","状态冲突"],
           ["10-29 09:40","管理员","商品审核","G-1021","待审核 → 已发布","成功"]],55)
    txt(c,290,722,"普通学生不能访问全局日志；交易统计不计入取消、拒绝、超时或违规终止。",13,MUTED)


SCREENS = [
    ("01_注册登录", login), ("02_商品浏览", browse),
    ("03_商品详情与预约", detail), ("04_卖家商品管理", seller_list),
    ("05_卖家处理预约", seller_booking), ("06_买家预约详情", buyer_booking),
    ("07_站内消息", inbox), ("08_提交举报", report_form),
    ("09_管理员商品审核", admin_review), ("10_管理员举报处理", admin_report),
    ("11_统计与日志", stats_log),
]


def main():
    poppler="/Users/kk/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/bin/pdftoppm"
    for name, draw in SCREENS:
        pdf=TMP/(name+".pdf")
        c=canvas.Canvas(str(pdf),pagesize=(W,H),pageCompression=1)
        draw(c); c.showPage(); c.save()
        subprocess.run([poppler,"-f","1","-singlefile","-png","-r","100",str(pdf),str(ROOT/name)],check=True)
        print(ROOT/(name+".png"))


if __name__ == "__main__":
    main()
