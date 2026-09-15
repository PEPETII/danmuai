// ESM 语法静态校验：只解析，不执行模块体。
// 用 vm.SourceTextModule 需要 --experimental-vm-modules。
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const files = process.argv.slice(2);

let bad = 0;
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  try {
    // 构造但不链接/求值：仅做语法解析
    new vm.SourceTextModule(src, { identifier: f });
    console.log(`OK    ${f}`);
  } catch (err) {
    bad += 1;
    console.log(`FAIL  ${f} -> ${err.message}`);
  }
}
console.log(bad === 0 ? 'ALL_MODULES_PARSE_OK' : `MODULE_PARSE_FAILURES=${bad}`);
process.exitCode = bad === 0 ? 0 : 1;
