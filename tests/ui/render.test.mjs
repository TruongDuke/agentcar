// Kiểm tra TẦNG HIỂN THỊ — 441 dòng index.html trước nay không có test nào, và
// trong một buổi đã lòi ra bốn lỗi ở đây: cốp trước viết cứng "không hỗ trợ",
// thẻ nhiều vùng chỉ đọc vùng mặc định, thiếu Cache-Control, Enter gửi hai lượt.
// Bộ đo 24.851 câu không bắt được cái nào: nó chấm JSON của lệnh, không mở
// trình duyệt.
//
// Chạy: node tests/ui/render.test.mjs   (hoặc qua pytest, xem tests/test_ui.py)
import { napTrang } from './load.mjs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const GOC = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const IDS = ['#devices', '#log', '#chips', '#gears', '#safety-hint'];

let hong = 0;
const kiem = (ten, fn) => {
  try { fn(); console.log(`  ✓ ${ten}`); }
  catch (e) { hong++; console.log(`  ✗ ${ten}\n      ${e.message}`); }
};
const bang = (a, b, vi) => {
  if (a !== b) throw new Error(`${vi}\n      cần : ${JSON.stringify(b)}\n      được: ${JSON.stringify(a)}`);
};
const chua = (a, b, vi) => {
  if (!String(a).includes(b)) throw new Error(`${vi}\n      cần chứa: ${JSON.stringify(b)}\n      được    : ${JSON.stringify(a)}`);
};

/** Dựng trang với một LAYOUT/STATE cho sẵn rồi trả về các thẻ đã vẽ. */
function ve({ devices, states, vehicle }) {
  const { ctx, kho, dat } = napTrang(join(GOC, 'agentcar', 'web', 'index.html'), IDS);
  dat('LAYOUT', {
    // khoá đúng như /api/layout trả về
    model: 'VF9', llm: true, deadline_ms: 1200, devices, safety: [],
  });
  dat('STATE', {
    devices: states,
    vehicle: vehicle ?? { gear: 'P', speed_kmh: 0, battery_pct: 100,
                          charging: false, parking_brake: 'engaged' },
    pending: null,
  });
  ctx.render();
  return { kho, the: kho.get('#devices').children };
}

const VOLUME = {
  device: 'volume', label: 'âm lượng', default_zone: 'all', supported: true,
  actions: ['set_level', 'increase', 'decrease', 'query'],
  zones: [{ zone: 'all', label: 'tất cả' }, { zone: 'va', label: 'trợ lý ảo' },
          { zone: 'media', label: 'nhạc' }],
  value: { kind: 'number', unit: 'level', lo: 0, hi: 40 },
};
const HUD = { device: 'hud', label: 'hud', supported: false, actions: [], zones: [] };

console.log('tầng hiển thị:');

kiem('vùng KHÁC mặc định đang bật thì thẻ phải hiện ra, không báo "tắt"', () => {
  const { the } = ve({
    devices: [VOLUME],
    states: [{ device: 'volume', zone: 'all', on: false, value: null },
             { device: 'volume', zone: 'va', on: true, value: 20, unit: 'level' },
             { device: 'volume', zone: 'media', on: true, value: 30, unit: 'level' }],
  });
  const chu = the[0].chu;
  if (/\btắt\b/.test(chu)) throw new Error(`thẻ báo "tắt" trong khi hai vùng đang bật\n      được: ${chu}`);
  chua(chu, 'trợ lý ảo', 'thiếu tên vùng va');
  chua(chu, 'nhạc', 'thiếu tên vùng media');
  chua(chu, '20', 'thiếu mức của vùng va');
});

kiem('không vùng nào bật thì vẫn báo "tắt" như cũ', () => {
  const { the } = ve({
    devices: [VOLUME],
    states: [{ device: 'volume', zone: 'all', on: false, value: null }],
  });
  chua(the[0].chu, 'tắt', 'mất trạng thái tắt');
});

kiem('thiết bị xe KHÔNG có thì nói "không hỗ trợ"', () => {
  const { the } = ve({ devices: [HUD], states: [] });
  chua(the[0].chu, 'không hỗ trợ', 'hud phải báo không hỗ trợ');
});

kiem('cốp trước đọc trạng thái THẬT, không phải chữ viết cứng', () => {
  for (const [on, mong] of [[true, 'mở'], [false, 'đóng']]) {
    const { kho } = ve({
      devices: [], states: [{ device: 'frunk', zone: null, on, value: null }],
    });
    const chu = kho.get('#s-frunk').chu;
    if (/không hỗ trợ/.test(chu))
      throw new Error(`cốp trước vẫn viết cứng "không hỗ trợ" (caps khai CÓ hỗ trợ từ 28/09)`);
    chua(chu, mong, `cốp trước on=${on}`);
  }
});

console.log(hong ? `\n${hong} mục HỎNG` : '\ntất cả đạt');
process.exit(hong ? 1 : 0);
