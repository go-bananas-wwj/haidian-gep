# 海淀区2024 GEP数据工作台

本仓库提供参考数据校验、来源目录、下载回执、缺数人工审核示例、冻结数据包发布，以及证据优先的 2024 海淀 GEP 任务 Demo。当前不产出海淀实际总 GEP；缺少真实输入时，服务会明确阻断快照与运行。

## 可运行任务 Demo

任务服务以 SQLite（WAL）持久化任务、三类 22 科目、节点版本、来源证据、审核、事件、补充工作单与快照。新任务会载入已核实的玉米产量来源（年鉴表 5-11、印刷第 71 页、2935.1 t/a）；价格和成本未提供，因此正式快照会被阻断。教学水产和原型构造数值不进入此服务。

```bash
python -m gep serve --database ./runtime/tasks.sqlite3
# 浏览 http://127.0.0.1:8000/
```

接口包括创建任务、读取图与事件、查看节点证据、审核、修正、幂等补充请求和冻结快照。Dify 未配置时，补充工作单只会以 `blocked` 状态保存，不会创建模拟结果。容器部署和恢复约束见 [deploy/README.md](deploy/README.md)。

## 安装与检查

Python 3.11+，已在3.12测试；基础功能使用标准库。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m unittest discover -s tests -v
python -m gep --help
```

仓库使用私有可见性。获得权限后通过本机凭据管理器访问，远端URL使用 `https://github.com/go-bananas-wwj/haidian-gep.git`。令牌只在环境变量或凭据管理器中使用。

## 数据整理

数据目录放在仓库外，例如 `../data/haidian_gep_2024`，分为 `00_catalog`、`01_raw`、`02_clean`、`03_features`、`04_docs`、`05_release`。

```bash
export GEP_DATA_ROOT="$PWD/../data/haidian_gep_2024"
python -m gep fetch yearbook --root "$GEP_DATA_ROOT"
python -m gep fetch aef-readme --root "$GEP_DATA_ROOT"
python -m gep fetch aef-index --root "$GEP_DATA_ROOT"
python -m gep check "$GEP_DATA_ROOT/02_clean/statistics/yearbook_2024_selected.csv"
python -m gep build "$GEP_DATA_ROOT/02_clean/statistics/yearbook_2024_selected.csv" --out "$GEP_DATA_ROOT/00_catalog/yearbook_catalog.json"
```

`fetch`拒绝覆盖原件；失败时保留`.partial`供排查，核对后移走该临时文件再重试。下载完成保存SHA-256回执。年鉴扫描页转录、字段字典和来源核验步骤见[详细实施方案](docs/implementation.tex)和[数据获取说明](docs/data-acquisition.md)。`check`验证结构与约束，不替代人工逐值复核。`observed`表示已转录事实，不代表核算所需的所有条件通过。空白不补零，口径冲突进入`pending`。

## 可运行的两科目教学示例

```bash
python -m gep example --out runs/example-01.json
python -m gep resolve runs/example-01.json --input examples/fish-area-yield.json --out runs/example-02.json
python -m gep approve runs/example-02.json --reviewer reviewer --out runs/example-03.json
```

玉米产量2935.1吨引用年鉴表5-11，其价格2000元/吨及全部投入是合成值，示例残值1870200元。水产原表空白；选择12公顷×5吨/公顷得到60吨待审，独立姓名审核后仍缺价格与投入。所有示例固定为`synthetic_training`，`gep_total=null`。另有投苗估算输入`examples/fish-stock.json`。

每次修改新建run并保留parent_run_id，禁止覆盖文件。CLI审核姓名用于工作流演示，不构成身份认证；正式产品的登录权限、电子证据及22科目计算需另行实现。

## 数据发布

目标：[WeijieWu/haidian_GEP](https://modelscope.cn/datasets/WeijieWu/haidian_GEP)。首次发布为参考资料包，完整核算数据仍需补齐。原始年鉴ZIP/PDF留本地，公开包只放经复核的统计事实、待确认项、来源链接、字典、方法和质量报告。人工审查许可后，将允许公开文件复制到独立目录，再执行：

```bash
python -m pip install -r requirements-publish.txt
export GEP_RELEASE_DIR="$GEP_DATA_ROOT/05_release/reference-2024-v0.1"
python -m gep seal "$GEP_RELEASE_DIR" --id reference-2024-v0.1
python -m gep verify-release "$GEP_RELEASE_DIR"
read -rsp 'ModelScope token: ' MODELSCOPE_TOKEN
export MODELSCOPE_TOKEN
python -m gep upload "$GEP_RELEASE_DIR" --repo WeijieWu/haidian_GEP
unset MODELSCOPE_TOKEN
```

先校验并冻结，再提交代码与Overleaf文档，最后上传。同一版本只允许一个发布进程，避免先查后写的并发竞争。发布使用临时快照与严格文件清单。SDK固定`modelscope-hub==0.4.3`，禁止覆盖已有版本路径，不启用同步删除，上传后回下载全部文件验证哈希。首版发布器只接受`.md/.json/.csv/.sha256/.txt`文本型参考包，拒绝符号链接、隐藏文件、常见令牌模式及清单外文件。扫描只是辅助，原件许可和敏感内容由人工复核。后续遥感大文件需新增经过验收的发布路径。

清单只保证传输完整性；人工核算适用性审核独立保存。上传中断可能在远端留下部分文件，查看远端状态后改用新版本号，不尝试自动删除或覆盖。发布回执保存在本地清单目录，不写回冻结包。

## 环境和文档

- `pyproject.toml`：基础包，无第三方运行依赖。
- `requirements-publish.txt`：发布SDK版本，环境快照见`docs/environment-publish.txt`。
- `Dockerfile`：Python 3.12镜像构建配方；本次验证以本地venv为准，未宣称容器构建通过。
- `docs/implementation.tex`：Overleaf详细方案副本，含获取步骤、国标方法、PRD和用户算例。
- `docs/validation.md`：本次验证范围及限制。

遥感下载后的筛选与裁切需独立GeoPandas/GDAL环境和经确认的海淀边界，基础CLI没有自动处理全部遥感或估算真实GEP。
