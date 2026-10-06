// DOM tối giản, đủ cho phần dựng giao diện của agentcar/web/index.html.
// Không dùng trình duyệt thật: chỉ cần biết trang VIẾT RA CHỮ GÌ, mà chuyện đó
// nằm trong textContent/innerHTML/className — không cần layout, không cần CSS.
class El {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this._cls = new Set();
    this._text = ''; this._html = ''; this.value = ''; this.disabled = false;
    this.style = {}; this.title = '';
    this.classList = {
      add: (...c) => c.forEach(x => this._cls.add(x)),
      remove: (...c) => c.forEach(x => this._cls.delete(x)),
      toggle: (c, on) => (on ?? !this._cls.has(c)) ? this._cls.add(c) : this._cls.delete(c),
      contains: (c) => this._cls.has(c),
    };
  }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._cls].join(' '); }
  set textContent(v) { this._text = String(v ?? ''); this.children = []; }
  get textContent() { return this._text || this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this._html = String(v ?? ''); if (v === '') this.children = []; }
  get innerHTML() { return this._html; }
  appendChild(c) { this.children.push(c); return c; }
  // Thanh cửa kính gọi el.querySelector('i'/'span') để đặt chiều cao. Trả về
  // một thẻ rỗng là đủ — bài test này đo CHỮ, không đo hình.
  querySelector() { return new El(); }
  prepend(c) { this.children.unshift(c); return c; }
  /** Mọi chữ thấy được trong thẻ này và con cháu — thứ người dùng thật sự đọc. */
  get chu() {
    const tu_html = this._html.replace(/<[^>]*>/g, ' ');
    return [this._text, tu_html, ...this.children.map(c => c.chu)]
      .join(' ').replace(/\s+/g, ' ').trim();
  }
}

export function dungDom(ids) {
  const kho = new Map(ids.map(i => [i, new El()]));
  const document = {
    hidden: false,
    createElement: (t) => new El(t),
    querySelector: (s) => kho.get(s) ?? kho.set(s, new El()).get(s),
    addEventListener: () => {},
  };
  return { document, kho };
}
