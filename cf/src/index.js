/**
 * Minny Bot — Cloudflare Worker
 * Handles Telegram webhook + Dashboard Admin API
 * D1 native binding (no REST API needed)
 */

// ═══════════════════════════════════════════
// D1 Helpers
// ═══════════════════════════════════════════

async function initTables(db) {
  await db.prepare(`CREATE TABLE IF NOT EXISTS knowledge (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL DEFAULT '',
    image_b64  TEXT NOT NULL DEFAULT '',
    added_by   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
  )`).run();

  await db.prepare(`CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
  )`).run();

  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id)`).run();

  await db.prepare(`CREATE TABLE IF NOT EXISTS user_profiles (
    chat_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
  )`).run();
}

async function getAllKnowledge(db) {
  const { results } = await db.prepare(
    'SELECT id, content, image_b64, added_by, created_at FROM knowledge ORDER BY id DESC'
  ).all();
  return results || [];
}

async function saveKnowledge(db, content, image_b64 = '', added_by = '') {
  const now = new Date().toISOString();
  const { meta } = await db.prepare(
    'INSERT INTO knowledge (content, image_b64, added_by, created_at) VALUES (?, ?, ?, ?)'
  ).bind(content, image_b64, added_by, now).run();
  return meta.last_row_id;
}

async function deleteKnowledge(db, id) {
  const { meta } = await db.prepare('DELETE FROM knowledge WHERE id = ?').bind(id).run();
  return meta.changes > 0;
}

async function getHistory(db, userId) {
  const { results } = await db.prepare(
    'SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id ASC'
  ).bind(String(userId)).all();
  return results || [];
}

async function addMessage(db, userId, role, content) {
  const now = new Date().toISOString();
  await db.prepare(
    'INSERT INTO conversations (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)'
  ).bind(String(userId), role, content, now).run();
  // Keep last 10 messages per chat
  await db.prepare(`
    DELETE FROM conversations WHERE chat_id = ? AND id NOT IN (
      SELECT id FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT 10
    )
  `).bind(String(userId), String(userId)).run();
}

async function clearHistory(db, chatId) {
  await db.prepare('DELETE FROM conversations WHERE chat_id = ?').bind(String(chatId)).run();
}

async function getAllUsers(db) {
  const { results } = await db.prepare(
    'SELECT chat_id, name, role, notes, updated_at FROM user_profiles ORDER BY updated_at DESC'
  ).all();
  return results || [];
}

async function saveUser(db, chatId, name = '', role = '', notes = '') {
  const now = new Date().toISOString();
  await db.prepare(`
    INSERT INTO user_profiles (chat_id, name, role, notes, updated_at) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET
      name=excluded.name, role=excluded.role,
      notes=excluded.notes, updated_at=excluded.updated_at
  `).bind(String(chatId), name, role, notes, now).run();
}

async function getUser(db, chatId) {
  const { results } = await db.prepare(
    'SELECT chat_id, name, role, notes, updated_at FROM user_profiles WHERE chat_id = ?'
  ).bind(String(chatId)).all();
  return results?.[0] || null;
}

async function deleteUser(db, chatId) {
  const { meta } = await db.prepare(
    'DELETE FROM user_profiles WHERE chat_id = ?'
  ).bind(String(chatId)).run();
  return meta.changes > 0;
}

// ═══════════════════════════════════════════
// Google Sheets Integration
// ═══════════════════════════════════════════

const THAI_MONTH_SHORT = {
  'ม.ค.':1,'ก.พ.':2,'มี.ค.':3,'เม.ย.':4,'พ.ค.':5,'มิ.ย.':6,
  'ก.ค.':7,'ส.ค.':8,'ก.ย.':9,'ต.ค.':10,'พ.ย.':11,'ธ.ค.':12,
  'มค':1,'กพ':2,'มีค':3,'เมย':4,'พค':5,'มิย':6,
  'กค':7,'สค':8,'กย':9,'ตค':10,'พย':11,'ธค':12,
};
const THAI_MONTH_FULL = {
  'มกราคม':1,'กุมภาพันธ์':2,'มีนาคม':3,'เมษายน':4,
  'พฤษภาคม':5,'มิถุนายน':6,'กรกฎาคม':7,'สิงหาคม':8,
  'กันยายน':9,'ตุลาคม':10,'พฤศจิกายน':11,'ธันวาคม':12,
};

function parseThaiDate(value) {
  if (!value) return null;
  value = String(value).trim();
  if (!value) return null;

  // Thai month name
  const allMonths = { ...THAI_MONTH_FULL, ...THAI_MONTH_SHORT };
  const sortedKeys = Object.keys(allMonths).sort((a, b) => b.length - a.length);
  for (const th of sortedKeys) {
    if (value.includes(th)) {
      const month = allMonths[th];
      const nums = value.match(/\d+/g);
      if (nums && nums.length >= 2) {
        const day = parseInt(nums[0]);
        let year = parseInt(nums[1]);
        if (year <= 100) year += 2000;
        if (year > 2400) year -= 543; // Buddhist Era
        return new Date(year, month - 1, day);
      }
    }
  }

  // Numeric formats
  const part = value.split(',')[0].trim();
  let m = part.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return new Date(+m[1], +m[2]-1, +m[3]);
  m = part.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
  if (m) return new Date(+m[3], +m[2]-1, +m[1]);
  m = part.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2})$/);
  if (m) return new Date(2000 + +m[3], +m[2]-1, +m[1]);

  return null;
}

function fmtDate(d) {
  return `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}`;
}

async function getGoogleToken(credJson) {
  const cred = JSON.parse(credJson);
  const scope = 'https://www.googleapis.com/auth/spreadsheets.readonly';
  const now = Math.floor(Date.now() / 1000);
  const header = btoa(JSON.stringify({ alg:'RS256', typ:'JWT' })).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
  const claim  = btoa(JSON.stringify({ iss:cred.client_email, scope, aud:'https://oauth2.googleapis.com/token', iat:now, exp:now+3600 })).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
  const input  = `${header}.${claim}`;

  const pem = cred.private_key.replace('-----BEGIN PRIVATE KEY-----','').replace('-----END PRIVATE KEY-----','').replace(/\s/g,'');
  const der = Uint8Array.from(atob(pem), c => c.charCodeAt(0));
  const key = await crypto.subtle.importKey('pkcs8', der.buffer, { name:'RSASSA-PKCS1-v1_5', hash:'SHA-256' }, false, ['sign']);
  const sig  = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(input));
  let bin = ''; new Uint8Array(sig).forEach(b => bin += String.fromCharCode(b));
  const b64sig = btoa(bin).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
  const jwt = `${input}.${b64sig}`;

  const resp = await fetch('https://oauth2.googleapis.com/token', {
    method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:`grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=${jwt}`,
  });
  const data = await resp.json();
  if (!data.access_token) throw new Error('Google auth failed: ' + JSON.stringify(data));
  return data.access_token;
}

async function fetchSheetRows(credJson, sheetId) {
  const token = await getGoogleToken(credJson);
  const sn = encodeURIComponent('หมดอายุ VIP');
  const resp = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${sn}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await resp.json();
  const rows = data.values || [];
  if (rows.length < 2) return [];
  const headers = rows[0];
  return rows.slice(1).map(row => Object.fromEntries(headers.map((h,i) => [h, row[i]||''])));
}

async function queryExpiry(text, credJson, sheetId) {
  const today = new Date(); today.setHours(0,0,0,0);
  const rows = await fetchSheetRows(credJson, sheetId);

  let filterFn;
  if (text.includes('สัปดาห์หน้า') || text.includes('อาทิตย์หน้า')) {
    const cut = new Date(today); cut.setDate(cut.getDate()+7);
    filterFn = d => d >= today && d <= cut;
  } else if (text.includes('เดือนหน้า')) {
    let nm = today.getMonth()+2, ny = today.getFullYear();
    if (nm > 12) { nm=1; ny++; }
    filterFn = d => d.getFullYear()===ny && d.getMonth()+1===nm;
  } else if (text.includes('เดือนนี้')) {
    filterFn = d => d.getFullYear()===today.getFullYear() && d.getMonth()===today.getMonth();
  } else {
    // เลขเดือน
    const mm = text.match(/เดือน(?:ที่)?\s*(\d{1,2})/);
    if (mm) {
      const mn = +mm[1];
      const yr = today.getFullYear() + (mn < today.getMonth()+1 ? 1 : 0);
      filterFn = d => d.getFullYear()===yr && d.getMonth()+1===mn;
    } else {
      // ชื่อเดือนไทย
      const allM = {...THAI_MONTH_FULL,...THAI_MONTH_SHORT};
      const found = Object.keys(allM).sort((a,b)=>b.length-a.length).find(k=>text.includes(k));
      if (found) {
        const mn = allM[found];
        const yr = today.getFullYear() + (mn < today.getMonth()+1 ? 1 : 0);
        filterFn = d => d.getFullYear()===yr && d.getMonth()+1===mn;
      } else {
        // default: 7 วัน
        const cut = new Date(today); cut.setDate(cut.getDate()+7);
        filterFn = d => d >= today && d <= cut;
      }
    }
  }

  const results = [];
  for (const row of rows) {
    const exp = parseThaiDate(row['วันหมดอายุ']);
    if (exp && filterFn(exp)) {
      results.push({
        shop: row['ชื่อกลุ่ม']||'',
        contact: row['เบอร์โทรศัพท์']||'',
        package: row['แพ็กเกจ']||'',
        expiry: fmtDate(exp),
        status: row['สถานะ']||'',
        _ts: exp.getTime(),
      });
    }
  }
  results.sort((a,b) => a._ts - b._ts);
  return results.map(({_ts,...r}) => r);
}

// ═══════════════════════════════════════════
// KB Matching (same logic as handlers.py)
// ═══════════════════════════════════════════

function kbMatches(question, content) {
  const q = question.toLowerCase().trim();
  if (!q || !content) return false;
  const firstLine = content.trim().split('\n')[0].toLowerCase();
  const keywords = firstLine.split(',').map(k => k.trim()).filter(k => k.length >= 2);
  for (const kw of keywords) {
    if (q.includes(kw) || kw.includes(q)) return true;
  }
  return false;
}

// ═══════════════════════════════════════════
// OpenAI / GPT
// ═══════════════════════════════════════════

async function callGPT(messages, apiKey, maxTokens = 800, temperature = 0.3) {
  const resp = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ model: 'gpt-4o-mini', messages, max_tokens: maxTokens, temperature }),
  });
  const data = await resp.json();
  return data.choices?.[0]?.message?.content?.trim() || '';
}

async function detectIntent(text, apiKey) {
  const system = `คุณเป็นระบบจำแนกประเภทคำถามของทีม Support บริษัท Thunder Solution
อ่านข้อความแล้วตอบแค่คำเดียว (ตัวพิมพ์ใหญ่):
TEACH    — เริ่มด้วย /teach หรือมีเจตนาสอนบอท
REMEMBER — บันทึก @username หรือแนะนำตัวเอง เช่น "จำ @somchai ชื่อ สมชาย" / "ฉันชื่อ สมชาย" / "X คือ Admin"
REWRITE  — มีคำว่า "เขียน" หรือ "แต่ง" หรือ "ร่าง" ข้อความ → REWRITE เสมอ แม้มีคำว่าหมดอายุ
EXPIRY   — ถามข้อมูลลูกค้าหมดอายุ (ไม่มีคำว่าเขียน/แต่ง/ร่าง)
QUERY    — ถามเรื่องสินค้า บริการ ฟีเจอร์ ราคา วิธีใช้
CHAT     — ทักทาย คุยเล่น ไม่เกี่ยวงาน
ข้อสงสัย → เลือก QUERY ตอบแค่คำเดียวเท่านั้น`;

  const result = await callGPT(
    [{ role: 'system', content: system }, { role: 'user', content: text }],
    apiKey, 10, 0
  );
  const upper = result.toUpperCase();
  for (const intent of ['TEACH', 'REMEMBER', 'QUERY', 'REWRITE', 'EXPIRY', 'CHAT']) {
    if (upper.includes(intent)) return intent;
  }
  return 'CHAT';
}

async function answerQuery(question, docs, history, apiKey, allUsers = []) {
  const context = docs.length
    ? docs.map((d, i) => `${i + 1}. ${d.content}`).join('\n')
    : '(ไม่มีข้อมูลใน knowledge base)';

  let system = `คุณคือ "น้องมินนี่" ผู้ช่วย Support ทีม Thunder Solution
- ดึงข้อมูลจาก knowledge base เท่านั้น ห้ามเพิ่ม ห้ามแต่งเอง
- ถ้าไม่มีใน KB: "ยังไม่มีข้อมูลเรื่องนี้ค่ะ"
- ห้ามใช้ * หรือ #`;
  if (allUsers.length) {
    const userLines = allUsers.filter(u => u.name).map(u => {
      const usernameTag = isNaN(u.chat_id) ? `@${u.chat_id}` : (u.notes || '');
      const alias = usernameTag ? `, Telegram: ${usernameTag}` : '';
      return `- ชื่อ: ${u.name}${alias}, role: ${u.role || 'ไม่ระบุ'}`;
    }).join('\n');
    if (userLines) system += `\n\n--- รายชื่อทีม ---\n${userLines}`;
  }
  system += `\n--- Knowledge Base ---\n${context}`;

  return await callGPT(
    [{ role: 'system', content: system }, ...history, { role: 'user', content: question }],
    apiKey, 800, 0.3
  );
}

async function chatReply(text, history, docs, apiKey, userProfile = null, allUsers = []) {
  let system = `คุณคือ "น้องมินนี่" ผู้ช่วย Support ทีม Thunder Solution
เป็นกันเอง สนุกสนาน ตอบตรง ห้ามใช้ * หรือ #`;
  if (userProfile?.name || userProfile?.role) {
    system += `\n\nผู้ที่คุยด้วยตอนนี้: ชื่อ "${userProfile.name || '-'}" role: ${userProfile.role || '-'}`;
  }
  if (allUsers.length) {
    const userLines = allUsers.filter(u => u.name).map(u => {
      const usernameTag = isNaN(u.chat_id) ? `@${u.chat_id}` : (u.notes || '');
      const alias = usernameTag ? `, Telegram: ${usernameTag}` : '';
      return `- ชื่อ: ${u.name}${alias}, role: ${u.role || 'ไม่ระบุ'}`;
    }).join('\n');
    if (userLines) system += `\n\n--- รายชื่อทีม ---\n${userLines}`;
  }
  if (docs.length) {
    system += '\n\n--- ข้อมูลที่รู้ ---\n' + docs.map(d => `- ${d.content}`).join('\n');
  }
  return await callGPT(
    [{ role: 'system', content: system }, ...history, { role: 'user', content: text }],
    apiKey, 400, 0.7
  );
}

async function rewriteMessage(raw, history, apiKey) {
  const system = `คุณคือ "น้องมินนี่" ผู้ช่วย Customer Support ทีม Thunder Solution โหมดเขียนข้อความถึงลูกค้า

กฎเหล็กรูปแบบข้อความ (ห้ามละเมิดทุกข้อ):
1. บรรทัดแรกของข้อความต้องเป็น "สวัสดีค่ะคุณลูกค้า 😊" เท่านั้น
2. บรรทัดสุดท้ายต้องเป็น "หากมีคำถามเพิ่มเติม แจ้งได้เลยนะคะ 😊" เท่านั้น
3. ในทุกจุดของข้อความ ใช้คำว่า "คุณลูกค้า" แทนลูกค้าเสมอ — ห้ามใส่ชื่อจริง ชื่อเล่น ชื่อกลุ่ม หรือชื่อร้านลงในข้อความไม่ว่ากรณีใด แม้ทีมงานจะพิมพ์ชื่อมาก็ตาม ให้แทนด้วย "คุณลูกค้า" เสมอ
4. ห้ามขึ้นต้นด้วย "เรียน" หรือ "เรียนคุณ" ทุกกรณี
5. ห้ามปิดท้ายด้วย "ขอบคุณค่ะ"
6. ห้ามใช้ * # ** markdown ทุกชนิด

เทมเพลตแจ้งหมดอายุ (ใช้เมื่อมีคำว่า หมดอายุ / แจ้งต่ออายุ / ต่ออายุบอท):
สวัสดีค่ะคุณลูกค้า 😊
ขออนุญาตแจ้งให้ทราบว่า ระบบบอทเช็คสลิปของคุณลูกค้าใกล้ครบกำหนดใช้งานแล้วค่ะ
โดยจะสิ้นสุดในวันที่ [วันที่ที่ทีมงานระบุ หรือจากข้อมูลที่มี]
หากคุณลูกค้าต้องการต่ออายุ สามารถแจ้งแอดมินเพื่อทำการต่ออายุได้เลยนะคะ 🙏💖
Thunder Solution ขอบพระคุณที่ไว้วางใจใช้บริการค่ะ
หากมีคำถามเพิ่มเติม แจ้งได้เลยนะคะ 😊

กฎการใช้เทมเพลตหมดอายุ:
- ถ้าทีมงานระบุวันที่มา ให้แทน [วันที่] ด้วยวันนั้น
- ถ้าไม่มีวันที่ ให้เว้นเป็น [ใส่วันที่] แทนการเดา
- ห้ามเปลี่ยน "คุณลูกค้า" เป็นชื่อจริง
- ห้ามตัดบรรทัด "Thunder Solution ขอบพระคุณ..."
- ห้ามใส่ราคาหรือโปรโมชั่นเพิ่มเองถ้าทีมงานไม่ได้ระบุ

โทนข้อความ: สุภาพ อบอุ่น ใส่ใจ ไม่ตำหนิลูกค้า ไม่ใส่มุก`;

  return await callGPT(
    [{ role: 'system', content: system }, ...history, { role: 'user', content: raw }],
    apiKey, 800, 0.4
  );
}

// ═══════════════════════════════════════════
// Telegram Helpers
// ═══════════════════════════════════════════

async function tgSend(chatId, text, token) {
  await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

async function tgSendPhoto(chatId, photoB64, caption, token) {
  const binary = atob(photoB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const form = new FormData();
  form.append('chat_id', String(chatId));
  form.append('photo', new Blob([bytes], { type: 'image/jpeg' }), 'photo.jpg');
  if (caption) form.append('caption', caption);

  await fetch(`https://api.telegram.org/bot${token}/sendPhoto`, { method: 'POST', body: form });
}

async function getImageB64(fileId, token) {
  const r1 = await fetch(`https://api.telegram.org/bot${token}/getFile?file_id=${fileId}`);
  const d1 = await r1.json();
  const filePath = d1.result?.file_path;
  if (!filePath) return '';
  const r2 = await fetch(`https://api.telegram.org/file/bot${token}/${filePath}`);
  const buf = await r2.arrayBuffer();
  let bin = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// ═══════════════════════════════════════════
// REMEMBER Parser
// ═══════════════════════════════════════════

function parseRemember(text, fromId = null) {
  // แบบ @username
  const m = text.match(/@(\w+)/);
  if (m) {
    const identifier = '@' + m[1].toLowerCase();
    let after = text.slice(m.index + m[0].length).trim();
    after = after.replace(/^(?:ชื่อ|คือ|=|ว่า|เป็น|ให้ชื่อ)\s*/i, '').trim();

    let role = '';
    const rm = after.match(/\b(admin|staff|vip|customer|other)\b/i);
    if (rm) {
      role = rm[1].toLowerCase();
      after = (after.slice(0, rm.index) + after.slice(rm.index + rm[0].length)).trim();
      after = after.replace(/\brole\b/i, '').trim();
    }

    if (!after) {
      let before = text.slice(0, m.index).trim();
      before = before.replace(/^(?:จำ|บันทึก|register|remember|เปลี่ยน)\s*/i, '').trim();
      before = before.replace(/\s*(?:ชื่อ|คือ|=|ว่า|เป็น)\s*$/i, '').trim();
      after = before;
    }

    const name = after.trim();
    if (!name && !role) return null;
    return { identifier, name, role };
  }

  // แบบไม่มี @ — บันทึกตัวเอง เช่น "ฉันชื่อ สมชาย" / "X คือ Admin"
  if (fromId) {
    let t = text.replace(/^(?:จำ|บันทึก|register|remember)\s*/i, '').trim();
    t = t.replace(/^(?:ฉัน(?:ชื่อ)?|ผม(?:ชื่อ)?|หนู(?:ชื่อ)?|น้อง(?:ชื่อ)?)\s*/i, '').trim();

    let role = '';
    const rm = t.match(/\b(admin|staff|vip|customer|other)\b/i);
    if (rm) {
      role = rm[1].toLowerCase();
      t = (t.slice(0, rm.index) + t.slice(rm.index + rm[0].length)).trim();
    }
    // "X คือ Y" หรือ "X เป็น Y"
    const kw = t.match(/^(.+?)\s*(?:คือ|เป็น|=)\s*(.*)$/i);
    if (kw) {
      const name = kw[1].trim();
      const extra = kw[2].trim();
      if (!role) {
        const rm2 = extra.match(/\b(admin|staff|vip|customer|other)\b/i);
        if (rm2) role = rm2[1].toLowerCase();
      }
      if (name) return { identifier: String(fromId), name, role };
    }
    t = t.replace(/\s*(?:คือ|เป็น|=)\s*.*/i, '').trim();
    if (t) return { identifier: String(fromId), name: t, role };
  }

  return null;
}

// ═══════════════════════════════════════════
// Message Handlers
// ═══════════════════════════════════════════

async function handleUpdate(update, env) {
  const message = update.message || update.edited_message;
  if (!message) return;

  const chatId = message.chat.id;           // ส่งข้อความไปที่นี่ (chat/group)
  const userId = String(message.from?.id || chatId); // lookup profile/history ตาม user จริง
  const text = (message.text || message.caption || '').trim();
  const { TELEGRAM_BOT_TOKEN: token, OPENAI_API_KEY: openaiKey, DB: db } = env;

  if (!text && !message.photo) {
    await tgSend(chatId, 'ส่ง caption มาด้วยนะ หรือพิมพ์คำถาม', token);
    return;
  }

  // ── Commands ──
  if (text === '/myid') { await handleMyId(message, env); return; }
  if (text === '/forget') { await clearHistory(db, userId); await tgSend(chatId, 'ลืมหมดแล้วนะ 🧹', token); return; }
  if (text === '/list') { await handleList(message, env); return; }

  const deleteM = text.match(/^\/delete\s+(\d+)$/);
  if (deleteM) {
    const ok = await deleteKnowledge(db, parseInt(deleteM[1]));
    await tgSend(chatId, ok ? `ลบ [${deleteM[1]}] แล้ว ✅` : `ไม่เจอ [${deleteM[1]}]`, token);
    return;
  }

  // ── /teach ──
  if (text.toLowerCase().startsWith('/teach') || (message.photo && text.startsWith('/teach'))) {
    await handleTeach(message, env); return;
  }

  // ── KB-first ──
  if (text) {
    const allKB = await getAllKnowledge(db);
    const matched = allKB.filter(d => kbMatches(text, d.content || ''));
    if (matched.length > 0) {
      const parts = matched.map(d => d.content.trim()).filter(Boolean);
      const images = matched.map(d => d.image_b64).filter(Boolean);
      const answerText = parts.join('\n\n');

      if (images.length > 0) {
        // ส่งรูปทุกรูปก่อน (ไม่ใส่ caption เพราะ content อาจยาวเกิน 1024 ตัว)
        for (const img of images) await tgSendPhoto(chatId, img, undefined, token);
        // ส่ง text แยกถ้ามี
        if (answerText) await tgSend(chatId, answerText, token);
      } else if (answerText) {
        await tgSend(chatId, answerText, token);
      }
      await addMessage(db, userId, 'user', text);
      await addMessage(db, userId, 'assistant', answerText);
      return;
    }
  }

  // ── User profile lookup — ลองทั้ง numeric ID และ @username ──
  const tgUsername = message.from?.username || '';
  let userProfile = await getUser(db, userId);
  if (!userProfile && tgUsername) {
    userProfile = await getUser(db, tgUsername);
  }
  // ถ้าเจอโปรไฟล์ผ่าน username → migrate ให้ใช้ numeric ID แทน
  if (userProfile && userProfile.chat_id !== userId) {
    await saveUser(db, userId, userProfile.name, userProfile.role, userProfile.notes || '');
    await deleteUser(db, userProfile.chat_id);
    userProfile.chat_id = userId;
  }

  // ── Intent detection ──
  const intent = await detectIntent(text, openaiKey);

  if (intent === 'TEACH') {
    await handleTeach(message, env);
  } else if (intent === 'REMEMBER') {
    await handleRemember(message, env);
  } else if (intent === 'EXPIRY') {
    if (env.GOOGLE_CRED && env.GOOGLE_SHEET_ID) {
      try {
        const rows = await queryExpiry(text, env.GOOGLE_CRED, env.GOOGLE_SHEET_ID);
        let reply;
        if (!rows.length) {
          reply = 'ไม่มีลูกค้าหมดอายุในช่วงนี้ 🎉';
        } else {
          const lines = [`พบลูกค้าหมดอายุ ${rows.length} ราย:\n`];
          for (const r of rows) {
            const st = r.status ? ` (${r.status})` : '';
            const pk = r.package ? `\n   แพ็กเกจ: ${r.package}` : '';
            lines.push(`🔴 ${r.shop}${pk}\n   หมดอายุ: ${r.expiry}${st}`);
          }
          reply = lines.join('\n\n');
        }
        await tgSend(chatId, reply, token);
        await addMessage(db, userId, 'user', text);
        await addMessage(db, userId, 'assistant', reply);
      } catch (e) {
        await tgSend(chatId, `โหลดข้อมูลหมดอายุไม่ได้: ${e.message}`, token);
      }
    } else {
      await tgSend(chatId, 'ยังไม่ได้เชื่อม Google Sheets นะ', token);
    }
  } else if (intent === 'REWRITE') {
    const history = await getHistory(db, userId);
    // ถ้า request เกี่ยวกับหมดอายุ → ใช้ template ตรงๆ ไม่ผ่าน GPT
    if (/หมดอายุ|ต่ออายุ|เตือนหมด|แจ้งหมด/.test(text)) {
      let dateStr = '[ใส่วันที่]';
      // ดึงวันที่จาก Sheets ถ้ามีชื่อลูกค้า
      if (env.GOOGLE_CRED && env.GOOGLE_SHEET_ID) {
        try {
          const words = text.toLowerCase().split(/\s+/).filter(w => w.length > 1);
          const rows = await fetchSheetRows(env.GOOGLE_CRED, env.GOOGLE_SHEET_ID);
          const found = rows.find(r => {
            const shop = (r['ชื่อกลุ่ม'] || '').toLowerCase();
            return words.some(w => w.length > 1 && shop.includes(w));
          });
          if (found) {
            const exp = parseThaiDate(found['วันหมดอายุ']);
            dateStr = exp ? fmtDate(exp) : (found['วันหมดอายุ'] || '[ใส่วันที่]');
          }
        } catch {}
      }
      // ดึงวันที่จาก text โดยตรงถ้าทีมงานพิมพ์มา (เช่น "25/06/2026" หรือ "25 มิถุนายน")
      const dateInText = text.match(/\d{1,2}\/\d{1,2}\/\d{4}/);
      if (dateInText) dateStr = dateInText[0];

      const reply = `สวัสดีค่ะคุณลูกค้า 😊\nขออนุญาตแจ้งให้ทราบว่า ระบบบอทเช็คสลิปของคุณลูกค้าใกล้ครบกำหนดใช้งานแล้วค่ะ\nโดยจะสิ้นสุดในวันที่ ${dateStr}\nหากคุณลูกค้าต้องการต่ออายุ สามารถแจ้งแอดมินเพื่อทำการต่ออายุได้เลยนะคะ 🙏💖\nThunder Solution ขอบพระคุณที่ไว้วางใจใช้บริการค่ะ\nหากมีคำถามเพิ่มเติม แจ้งได้เลยนะคะ 😊`;
      await tgSend(chatId, reply, token);
      await addMessage(db, userId, 'user', text);
      await addMessage(db, userId, 'assistant', reply);
    } else {
      const reply = await rewriteMessage(text, history, openaiKey);
      await tgSend(chatId, reply, token);
      await addMessage(db, userId, 'user', text);
      await addMessage(db, userId, 'assistant', reply);
    }
  } else if (intent === 'QUERY') {
    const [history, allKB, allUsers] = await Promise.all([getHistory(db, userId), getAllKnowledge(db), getAllUsers(db)]);
    const matched = allKB.filter(d => kbMatches(text, d.content || ''));
    const reply = await answerQuery(text, matched.length ? matched : allKB, history, openaiKey, allUsers);
    await tgSend(chatId, reply, token);
    await addMessage(db, userId, 'user', text);
    await addMessage(db, userId, 'assistant', reply);
  } else {
    const [history, allKB, allUsers] = await Promise.all([getHistory(db, userId), getAllKnowledge(db), getAllUsers(db)]);
    const reply = await chatReply(text, history, allKB, openaiKey, userProfile, allUsers);
    await tgSend(chatId, reply, token);
    await addMessage(db, userId, 'user', text);
    await addMessage(db, userId, 'assistant', reply);
  }
}

async function handleTeach(message, env) {
  const chatId = message.chat.id;
  const { TELEGRAM_BOT_TOKEN: token, DB: db } = env;

  let content = (message.text || message.caption || '').replace(/^\/teach\s*/i, '').trim();
  let imageB64 = '';

  if (message.photo) {
    try {
      imageB64 = await getImageB64(message.photo[message.photo.length - 1].file_id, token);
    } catch {
      await tgSend(chatId, 'โหลดรูปไม่สำเร็จ ลองใหม่นะ', token); return;
    }
  }

  if (!content && !imageB64) {
    await tgSend(chatId, 'ส่งข้อมูลมาด้วยนะ เช่น /teach วิธีต่ออายุคือ...', token); return;
  }

  const user = message.from;
  const addedBy = user.username || user.first_name || String(user.id);
  await saveKnowledge(db, content, imageB64, addedBy);
  await tgSend(chatId, 'บันทึกแล้วนะ 👍', token);
}

async function handleRemember(message, env) {
  const chatId = message.chat.id;
  const { TELEGRAM_BOT_TOKEN: token, DB: db } = env;
  const text = (message.text || '').trim();
  const fromId = message.from?.id;

  const parsed = parseRemember(text, fromId);
  if (!parsed) {
    await tgSend(chatId, 'ไม่เข้าใจรูปแบบนะ ลองพิมพ์:\nจำ @somchai ชื่อ สมชาย\n@somchai คือ สมชาย staff', token);
    return;
  }
  await saveUser(db, parsed.identifier, parsed.name, parsed.role, '');
  const parts = [];
  if (parsed.name) parts.push(`ชื่อ: ${parsed.name}`);
  if (parsed.role) parts.push(`Role: ${parsed.role}`);
  await tgSend(chatId, `จำแล้วนะ ${parsed.identifier}\n${parts.join('\n')}`, token);
}

async function handleMyId(message, env) {
  const chatId = message.chat.id;
  const { TELEGRAM_BOT_TOKEN: token, DB: db } = env;
  const user = message.from;
  const tgUsername = user.username ? '@' + user.username.toLowerCase() : null;

  let linkedMsg = '';
  if (tgUsername) {
    const old = await getUser(db, tgUsername);
    if (old) {
      await saveUser(db, String(chatId), old.name, old.role, old.notes);
      await deleteUser(db, tgUsername);
      linkedMsg = `\nเชื่อมข้อมูลจาก ${tgUsername} แล้ว`;
    }
  }

  const profile = await getUser(db, String(chatId));
  let profileMsg = '';
  if (profile?.name || profile?.role) {
    profileMsg = `\n\nระบบรู้จักว่า:\nชื่อ: ${profile.name || '-'}\nRole: ${profile.role || '-'}`;
  }

  await tgSend(chatId,
    `Chat ID ของคุณคือ:\n${chatId}\n\nชื่อ: ${user.first_name || '-'}\nUsername: ${tgUsername || '(ไม่มี)'}${linkedMsg}${profileMsg}\n\nคัดลอก Chat ID ไปใส่ Dashboard ได้เลย`,
    token
  );
}

async function handleList(message, env) {
  const chatId = message.chat.id;
  const { TELEGRAM_BOT_TOKEN: token, DB: db } = env;
  const docs = await getAllKnowledge(db);
  if (!docs.length) { await tgSend(chatId, 'ยังไม่มี knowledge เลย', token); return; }
  const lines = [`📚 Knowledge ทั้งหมด (${docs.length} รายการ)\n`];
  for (const doc of docs) {
    const c = doc.content || '(ไม่มีข้อความ)';
    lines.push(`[${doc.id}] ${c.slice(0, 80)}${c.length > 80 ? '...' : ''}`);
  }
  lines.push('\nลบรายการ: /delete [id]');
  await tgSend(chatId, lines.join('\n'), token);
}

// ═══════════════════════════════════════════
// Main Router
// ═══════════════════════════════════════════

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const { pathname } = url;
    const method = request.method;

    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    };

    if (method === 'OPTIONS') return new Response('', { headers: cors });

    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json', ...cors },
      });

    // Init tables on first request
    try { await initTables(env.DB); } catch {}

    try {
      // ── Telegram Webhook ──
      if (pathname === '/webhook' && method === 'POST') {
        const update = await request.json();
        ctx.waitUntil(handleUpdate(update, env));
        return new Response('OK');
      }

      // ── Knowledge Base ──
      if (pathname === '/api/knowledge') {
        if (method === 'GET') {
          const docs = await getAllKnowledge(env.DB);
          return json(docs.map(d => ({ ...d, has_image: !!d.image_b64, image_b64: undefined })));
        }
        if (method === 'POST') {
          const data = await request.json();
          const id = await saveKnowledge(env.DB, data.content || '', data.image_b64 || '', data.added_by || 'dashboard');
          return json({ id });
        }
      }

      if (pathname.match(/^\/api\/knowledge\/\d+$/)) {
        const id = parseInt(pathname.split('/')[3]);
        if (method === 'DELETE') {
          const ok = await deleteKnowledge(env.DB, id);
          return json({ ok });
        }
        if (method === 'PUT') {
          const data = await request.json();
          await env.DB.prepare('UPDATE knowledge SET content = ? WHERE id = ?')
            .bind(data.content || '', id).run();
          return json({ ok: true });
        }
      }

      // ── History ──
      if (pathname.startsWith('/api/history/')) {
        const chatId = decodeURIComponent(pathname.split('/')[3]);
        if (method === 'GET') return json(await getHistory(env.DB, chatId));
        if (method === 'DELETE') { await clearHistory(env.DB, chatId); return json({ ok: true }); }
      }

      // ── Users ──
      if (pathname === '/api/users') {
        if (method === 'GET') return json(await getAllUsers(env.DB));
        if (method === 'POST') {
          const data = await request.json();
          if (!data.chat_id) return json({ error: 'chat_id required' }, 400);
          await saveUser(env.DB, data.chat_id, data.name || '', data.role || '', data.notes || '');
          return json({ ok: true });
        }
      }

      if (pathname.startsWith('/api/users/') && method === 'DELETE') {
        const chatId = decodeURIComponent(pathname.split('/')[3]);
        return json({ ok: await deleteUser(env.DB, chatId) });
      }

      // ── Expiry (Google Sheets) ──
      if (pathname === '/api/expiry') {
        const q = url.searchParams.get('q') || '7 วัน';
        if (!env.GOOGLE_CRED || !env.GOOGLE_SHEET_ID) return json([]);
        try {
          const rows = await queryExpiry(q, env.GOOGLE_CRED, env.GOOGLE_SHEET_ID);
          return json(rows);
        } catch (e) {
          return json({ error: e.message }, 500);
        }
      }

      // ── Test Bot ──
      if (pathname === '/api/query' && method === 'POST') {
        const data = await request.json();
        const q = (data.question || '').trim();
        if (!q) return json({ error: 'no question' }, 400);
        const allKB = await getAllKnowledge(env.DB);
        const matched = allKB.filter(d => kbMatches(q, d.content || ''));
        if (matched.length) {
          return json({
            answer: matched.map(d => d.content).join('\n\n'),
            mode: 'verbatim', kb_hit: true,
            has_image: matched.some(d => !!d.image_b64),
          });
        }
        const answer = await answerQuery(q, allKB, [], env.OPENAI_API_KEY);
        return json({ answer, mode: 'gpt', kb_hit: false, has_image: false });
      }

      // ── Static assets (dashboard.html) ──
      return env.ASSETS.fetch(request);

    } catch (e) {
      return json({ error: e.message }, 500);
    }
  },
};
