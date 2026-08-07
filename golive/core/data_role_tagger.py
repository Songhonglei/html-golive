"""
data_role_tagger.py
-------------------
自动为 HTML 骨架元素添加 data-role 属性，供 CSS 增强模块使用。

data-role 语义标签：
  container    — 页面最外层包裹容器
  header       — 顶栏（含 logo + 标题 + 副标题）
  header-logo  — logo / 图标区域
  header-title — 顶栏主标题
  header-meta  — 顶栏右侧元信息（日期、作者等）
  page-title   — 正文主标题（h1 级别）
  page-subtitle — 正文副标题 / 摘要
  section      — 页面内独立区块 / 章节
  sidebar      — 侧边栏
  hero         — 封面大图 / banner / splash
  card-grid    — 卡片列表容器
  card         — 单张卡片
  card-header  — 卡片顶部（含徽章 + 标题 + 标签）
  card-badge   — 卡片序号 / 徽章
  card-title   — 卡片标题
  card-label   — 卡片标签 / 说明
  card-body    — 卡片内容区
  list-item    — 列表条目
  item-badge   — 条目序号方块（如 1/2/3 小圆角方块）
  item-title   — 条目标题
  item-desc    — 条目描述 / 次要文字
  stat-block   — 数据/KPI 指标块
  stat-value   — 核心数值
  stat-trend   — 趋势标签（涨跌/环比）
  tag-group    — 标签组容器
  tag-item     — 单个标签/chip/pill
  progress-bar — 进度条
  avatar       — 头像 / 用户图标
  media        — 图片/缩略图块
  quote        — 引用块
  callout      — 高亮提示/警告/tip 块
  button       — 按钮 / CTA
  form-field   — 表单输入项
  step-item    — 步骤条单步
  timeline     — 时间线容器
  tab-bar      — Tab 导航栏
  tab-item     — 单个 Tab
  bottom-nav   — 移动端底部导航栏
  toolbar      — 工具栏 / 操作栏
  breadcrumb   — 面包屑导航
  overlay        — 浮层 / 弹窗 / drawer
  overlay-header — 弹窗顶部标题栏
  overlay-title  — 弹窗标题文字
  overlay-body   — 弹窗内容区
  overlay-footer — 弹窗底部操作栏
  pagination     — 分页容器
  pagination-item — 分页按钮
  nav-item       — 侧边栏 / 顶部导航条目
  rating         — 评分 / 星级
  empty-state  — 空状态占位
  skeleton     — 骨架屏 / 加载态
  data-table   — 表格
  table-header — 表头
  table-row    — 表格行
  table-cell   — 表格单元格
  footer       — 底部总结区
  divider      — 分隔线
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag

from golive.i18n import t as _t


# ── 基于类名关键词的静态映射 ──────────────────────────────────
CLASS_ROLE_HINTS = {
    # 容器
    'sd': 'container', 'container': 'container', 'wrapper': 'container',
    'app': 'container', 'page': 'container', 'layout': 'container',
    'main': 'container', 'content': 'container',

    # 顶栏
    'hdr': 'header', 'header': 'header', 'nav': 'header',
    'navbar': 'header', 'topbar': 'header', 'top-bar': 'header',

    # logo
    'hdr-logo': 'header-logo', 'logo': 'header-logo', 'brand': 'header-logo',
    'topbar-brand': 'header-logo', 'navbar-brand': 'header-logo',

    # 顶栏标题
    't': None,   # 需要结合父级判断
    'hdr-title': 'header-title',
    'topbar-logo': 'header-title', 'navbar-title': 'header-title',

    # 顶栏右侧元信息
    'r': None,   # 需要结合父级判断
    'hdr-meta': 'header-meta', 'meta': 'header-meta',
    'hdr-r': 'header-meta', 'header-right': 'header-meta',

    # 页面主标题
    'h1': 'page-title', 'h2': 'page-title', 'title': 'page-title',
    'page-title': 'page-title',

    # 页面副标题
    'hsub': 'page-subtitle', 'subtitle': 'page-subtitle',
    'summary': 'page-subtitle', 'intro': 'page-subtitle',

    # 卡片容器（移除过于通用的 'list'，避免误匹配导航列表/普通ul）
    'cols': 'card-grid', 'cards': 'card-grid', 'grid': 'card-grid',
    'card-list': 'card-grid', 'card-grid': 'card-grid',

    # 卡片（移除过于通用的 'block'/'box'，避免误匹配 Bootstrap/Tailwind 布局类）
    'col': 'card', 'card': 'card', 'panel': 'card',
    'item-card': 'card',

    # 卡片头
    'col-h': 'card-header', 'card-header': 'card-header',
    'panel-header': 'card-header',

    # 卡片徽章
    'col-n': 'card-badge', 'badge': 'card-badge', 'num': 'card-badge',
    'index': 'card-badge', 'it-n-badge': 'card-badge', 'n-badge': 'card-badge',

    # 卡片标题
    'col-t': 'card-title', 'card-title': 'card-title',

    # 卡片标签（'label' 移到上下文推断，避免误匹配 form label）
    'col-d': 'card-label', 'tag': 'card-label',

    # 卡片内容
    'col-body': 'card-body', 'card-body': 'card-body',

    # 列表条目（移除 'row'，避免误匹配 Bootstrap .row 栅格容器）
    'it': 'list-item', 'list-item': 'list-item', 'entry': 'list-item',

    # 条目序号徽章
    'it-n': 'item-badge', 'item-num': 'item-badge', 'item-index': 'item-badge',
    'step-num': 'item-badge', 'step-badge': 'item-badge', 'order': 'item-badge',

    # 条目标题
    'it-t': 'item-title', 'item-title': 'item-title',

    # 条目描述
    'it-s': 'item-desc', 'item-desc': 'item-desc', 'item-sub': 'item-desc',
    'desc': 'item-desc',

    # 底部（移除 'bottom'/'end'，避免误匹配 Tailwind bottom-0 / flex-end 等定位类）
    'ftr': 'footer', 'footer': 'footer', 'conclusion': 'footer',

    # 分隔线
    'divider': 'divider', 'separator': 'divider', 'rule': 'divider',

    # 章节 / 区块
    'section': 'section', 'segment': 'section', 'area': 'section',
    'zone': 'section', 'region': 'section', 'module': 'section',

    # 侧边栏
    'sidebar': 'sidebar', 'aside': 'sidebar', 'side': 'sidebar',
    'side-panel': 'sidebar',

    # 封面大图 / banner
    'hero': 'hero', 'banner': 'hero', 'cover': 'hero',
    'splash': 'hero', 'jumbotron': 'hero',

    # 数据/KPI 指标块
    'kpi': 'stat-block', 'metric': 'stat-block', 'stat': 'stat-block',
    'stat-block': 'stat-block', 'data-card': 'stat-block',
    'indicator': 'stat-block', 'measure': 'stat-block',

    # 核心数值
    'value': 'stat-value', 'amount': 'stat-value', 'number': 'stat-value',
    'stat-value': 'stat-value', 'figure': 'stat-value', 'count': 'stat-value',
    'percent': 'stat-value', 'pct': 'stat-value',

    # 趋势标签
    'trend': 'stat-trend', 'change': 'stat-trend', 'delta': 'stat-trend',
    'growth': 'stat-trend', 'diff': 'stat-trend', 'vs': 'stat-trend',

    # 标签组
    'tags': 'tag-group', 'chips': 'tag-group', 'pills': 'tag-group',
    'tag-list': 'tag-group', 'keywords': 'tag-group',

    # 单个标签
    'tag': 'tag-item', 'chip': 'tag-item', 'pill': 'tag-item',
    'keyword': 'tag-item', 'topic': 'tag-item', 'category': 'tag-item',

    # 进度条（移除 'bar'，避免误匹配 navbar/topbar/sidebar 等）
    'progress': 'progress-bar', 'track': 'progress-bar',
    'progress-bar': 'progress-bar', 'gauge': 'progress-bar',

    # 头像
    'avatar': 'avatar', 'portrait': 'avatar', 'user-img': 'avatar',
    'user-avatar': 'avatar', 'profile-img': 'avatar', 'face': 'avatar',

    # 图片/媒体块
    'img': 'media', 'image': 'media', 'photo': 'media',
    'thumb': 'media', 'thumbnail': 'media', 'pic': 'media',
    'figure': 'media', 'media': 'media',

    # 引用块
    'quote': 'quote', 'blockquote': 'quote', 'cite': 'quote',
    'testimonial': 'quote', 'pullquote': 'quote',

    # 高亮提示 / callout
    'alert': 'callout', 'notice': 'callout', 'tip': 'callout',
    'warning': 'callout', 'info': 'callout', 'callout': 'callout',
    'highlight': 'callout', 'note': 'callout', 'hint': 'callout',

    # 按钮
    'btn': 'button', 'button': 'button', 'cta': 'button',
    'action': 'button', 'btn-primary': 'button', 'btn-secondary': 'button',

    # 表单输入项
    'input': 'form-field', 'field': 'form-field', 'form-item': 'form-field',
    'form-group': 'form-field', 'form-control': 'form-field',

    # 步骤条单步
    'step': 'step-item', 'step-item': 'step-item', 'stage': 'step-item',
    'phase': 'step-item', 'timeline-item': 'step-item',

    # 时间线容器
    'timeline': 'timeline', 'history': 'timeline', 'steps': 'timeline',
    'process': 'timeline', 'flow': 'timeline',

    # Tab 导航
    'tabs': 'tab-bar', 'tab-bar': 'tab-bar', 'tab-nav': 'tab-bar',
    'tab-list': 'tab-bar', 'nav-tabs': 'tab-bar',

    # 单个 Tab
    'tab': 'tab-item', 'tab-item': 'tab-item', 'tab-link': 'tab-item',

    # 移动端底部导航
    'bottom-nav': 'bottom-nav', 'tabbar': 'bottom-nav',
    'bottom-bar': 'bottom-nav', 'tab-bottom': 'bottom-nav',
    'footer-nav': 'bottom-nav',

    # 工具栏
    'toolbar': 'toolbar', 'action-bar': 'toolbar', 'controls': 'toolbar',
    'tool-bar': 'toolbar', 'ops': 'toolbar', 'actions': 'toolbar',

    # 面包屑
    'breadcrumb': 'breadcrumb', 'crumb': 'breadcrumb', 'crumbs': 'breadcrumb',
    'breadcrumbs': 'breadcrumb', 'path': 'breadcrumb',

    # 浮层 / 弹窗
    'modal': 'overlay', 'popup': 'overlay', 'overlay': 'overlay',
    'drawer': 'overlay', 'dialog': 'overlay', 'sheet': 'overlay',
    'dropdown': 'overlay', 'popover': 'overlay',
    'modal-overlay': 'overlay',

    # 弹窗子区域
    'modal-header': 'overlay-header', 'dialog-header': 'overlay-header',
    'modal-title': 'overlay-title', 'dialog-title': 'overlay-title',
    'modal-body': 'overlay-body', 'dialog-body': 'overlay-body',
    'modal-content': 'overlay-body', 'dialog-content': 'overlay-body',
    'modal-footer': 'overlay-footer', 'dialog-footer': 'overlay-footer',

    # 分页
    'pagination': 'pagination', 'pager': 'pagination', 'page-nav': 'pagination',
    'pages': 'pagination',
    'page-btn': 'pagination-item', 'page-item': 'pagination-item',

    # 导航条目
    'nav-item': 'nav-item', 'nav-link': 'nav-item', 'menu-item': 'nav-item',
    'sidebar-item': 'nav-item',

    # 搜索栏（映射到 toolbar）
    'search-bar': 'toolbar', 'search': 'toolbar', 'searchbar': 'toolbar',
    'filter-bar': 'toolbar', 'query-bar': 'toolbar',

    # 表格包裹容器
    'table-wrapper': 'data-table', 'table-scroll': 'data-table',

    # 评分
    'rating': 'rating', 'stars': 'rating', 'score': 'rating',
    'star-rating': 'rating',

    # 空状态
    'empty': 'empty-state', 'empty-state': 'empty-state',
    'placeholder': 'empty-state', 'no-data': 'empty-state',
    'no-content': 'empty-state',

    # 骨架屏 / 加载态
    'loading': 'skeleton', 'skeleton': 'skeleton', 'shimmer': 'skeleton',
    'loading-placeholder': 'skeleton', 'pulse': 'skeleton',

    # 表格
    'data-table': 'data-table', 'table-wrap': 'data-table',
    'table-container': 'data-table', 'grid-table': 'data-table',

    # 表头（class 形式，table 原生标签单独处理）
    'table-head': 'table-header', 'thead-row': 'table-header',
    'th-group': 'table-header',

    # 表格行
    'table-row': 'table-row', 'tr-item': 'table-row', 'data-row': 'table-row',

    # 表格单元格
    'cell': 'table-cell', 'td-cell': 'table-cell', 'table-cell': 'table-cell',
}


def _classes(el: Tag) -> list[str]:
    return el.get('class', []) if isinstance(el, Tag) else []


def _parent_role(el: Tag) -> str | None:
    p = el.parent
    if isinstance(p, Tag):
        return p.get('data-role')
    return None


def _assign_role(el: Tag) -> str | None:
    """根据类名 + 上下文推断 data-role"""
    classes = _classes(el)

    for cls in classes:
        hint = CLASS_ROLE_HINTS.get(cls)
        if hint:
            return hint

    # 需要父级上下文的特殊类
    parent_role = _parent_role(el)
    for cls in classes:
        if cls == 't':
            return 'header-title' if parent_role == 'header' else 'card-title'
        if cls == 'r':
            return 'header-meta' if parent_role == 'header' else None
        # 'item' 只在 card/card-grid/list 父级下才识别为 list-item，避免误匹配
        if cls == 'item':
            if parent_role in ('card', 'card-grid', 'card-body', 'list-item', None):
                return 'list-item' if parent_role in ('card', 'card-grid', 'card-body') else None
        # 'label' 只在 card-header/card 父级下才识别为 card-label，避免误匹配 form label
        if cls == 'label':
            if parent_role in ('card-header', 'card'):
                return 'card-label'

    # ── 原生 HTML 标签语义推断 ──────────────────────────────
    tag = el.name

    # 分隔线
    if tag == 'hr':
        return 'divider'

    # 表格结构
    if tag == 'table':
        return 'data-table'
    if tag == 'thead':
        return 'table-header'
    if tag == 'tr':
        parent_role = _parent_role(el)
        if parent_role == 'table-header':
            return 'table-header'
        return 'table-row'
    if tag in ('td', 'th'):
        return 'table-cell'

    # 媒体 / 引用
    if tag == 'figure':
        return 'media'
    if tag == 'figcaption':
        return 'item-desc'
    if tag == 'blockquote':
        return 'quote'

    # 按钮
    if tag == 'button':
        return 'button'

    # 输入框
    if tag in ('input', 'textarea', 'select'):
        return 'form-field'

    # 进度条
    if tag == 'progress':
        return 'progress-bar'

    # 图片（无类名）
    if tag == 'img':
        parent_role = _parent_role(el)
        # 在 header 里是 logo
        if parent_role == 'header':
            return 'header-logo'
        # 在 avatar 父元素里不重复标
        if parent_role in ('avatar', 'media'):
            return None
        return 'media'

    # 原生 nav 标签
    if tag == 'nav':
        return 'header'

    # 原生 aside
    if tag == 'aside':
        return 'sidebar'

    # 原生 section / article / main
    if tag in ('section', 'article'):
        return 'section'

    # 原生 time 标签
    if tag == 'time':
        return 'header-meta'

    # card-grid 的直接子 <div>（无类名）→ card
    # 处理 .cols > <div> 这种裸 div 列卡片骨架
    if tag == 'div' and not classes:
        parent_role = _parent_role(el)
        if parent_role == 'card-grid':
            return 'card'

    return None


def tag_html(html: str) -> str:
    """
    解析 HTML，为识别出的骨架元素添加 data-role，返回修改后的 HTML 字符串。
    已有 data-role 的元素跳过（不覆盖）。
    """
    soup = BeautifulSoup(html, 'html.parser')

    # BFS 遍历，从外向内，确保父级先打标
    queue = list(soup.find_all(True))
    tagged = 0
    for el in queue:
        if not isinstance(el, Tag):
            continue
        if el.get('data-role'):
            continue  # 已有标注，跳过
        role = _assign_role(el)
        if role:
            el['data-role'] = role
            tagged += 1

    return str(soup), tagged


if __name__ == '__main__':
    import sys, pathlib

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print(_t("tagger.usage"))
        sys.exit(1)

    src = pathlib.Path(path).read_text(encoding='utf-8')
    result, count = tag_html(src)

    out = pathlib.Path(path).with_suffix('.tagged.html')
    out.write_text(result, encoding='utf-8')
    print(_t("tagger.done", count=count, out=out))

    # 打印 data-role 分布
    soup2 = BeautifulSoup(result, 'html.parser')
    from collections import Counter
    roles = Counter(el.get('data-role') for el in soup2.find_all(True) if el.get('data-role'))
    for role, cnt in sorted(roles.items()):
        print(f"  {role}: {cnt}")
