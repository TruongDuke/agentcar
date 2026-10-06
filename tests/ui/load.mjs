// Nạp phần LOGIC của index.html vào Node, bỏ khối khởi động.
//
// Không sửa index.html: trang đó đang được dùng để demo, đổi cấu trúc file ngay
// trước buổi demo là rủi ro không đáng. Thay vào đó cắt đúng tại mốc "khởi
// động" — phần trên là hàm thuần, phần dưới gọi mạng và gắn sự kiện.
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { dungDom } from './dom.mjs';

const MOC = '// ---------------------------------------------------------------- khởi động';

export function napTrang(duong, ids) {
  const html = readFileSync(duong, 'utf8');
  const script = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));
  const cat = script.indexOf(MOC);
  if (cat < 0) throw new Error(`không tìm thấy mốc khởi động trong ${duong}`);

  const { document, kho } = dungDom(ids);
  const ctx = createContext({
    document, window: {}, console,
    setInterval: () => 0, setTimeout: () => 0, fetch: async () => ({ json: async () => ({}) }),
    SpeechSynthesisUtterance: class {}, speechSynthesis: { speak() {} },
  });
  runInContext(script.slice(0, cat), ctx);

  // `let LAYOUT, STATE` là ràng buộc TỪ VỰNG, không nằm trên đối tượng toàn cục
  // — gán ctx.STATE là tạo một biến khác, hàm render() vẫn thấy null. Phải gán
  // từ bên trong ngữ cảnh.
  const dat = (ten, gia_tri) => {
    ctx.__tam = gia_tri;
    runInContext(`${ten} = __tam;`, ctx);
  };
  return { ctx, kho, document, dat };
}
