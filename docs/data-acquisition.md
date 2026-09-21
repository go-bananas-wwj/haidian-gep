# 数据获取与输入归档

## 官方年鉴

入口：https://zyk.bjhd.gov.cn/sjkf/ndsj/202601/t20260104_4799659.shtml

`python -m gep fetch yearbook --root <数据根目录>` 固定官方2025年鉴附件URL。原ZIP保存在 `01_raw/statistics/`。执行 `python -m zipfile -t <ZIP>` 检查CRC，再查看目录并解压。扫描PDF逐页人工检查2024列、行名、单位与脚注。逐条记下表号、印刷页、PDF页、源文件。第1--9章PDF页与印刷页一致；第10--19章印刷页=PDF页+156。原件使用指南带转载限制，原始PDF/ZIP不进入公开发布。

提取CSV的11个字段为 `region_code,year,table_id,printed_page,pdf_page,source_file,metric,value,unit,status,notes`。当前43条，40条observed、2条blank_unresolved、1条scope_conflict。observed表示转录一致，仍需独立检查核算适用及来源边界。空白保留空值；5-4干鲜果3154.1吨与5-10总计3159.5吨的冲突单列，不静默选择。

## AlphaEarth

Source Cooperative：https://source.coop/tge-labs/aef

README：https://data.source.coop/tge-labs/aef/README.md

索引：https://data.source.coop/tge-labs/aef/v1/annual/aef_index.parquet

`fetch aef-readme` 和 `fetch aef-index`保存公开原件和获取回执。筛选索引year=2024及确认的海淀边界相交全部瓦片；检查实际列、CRS和路径，逐瓦片下载COG及配套VRT。README提示原始COG为bottom-up，按配套VRT纠正读向；VRT本地化后用GDAL裁切并检查全区有效覆盖。掩膜-128，转换浮点后 `sign(q)*(q/127.5)**2`，保留A00--A63。年度嵌入提供特征，NPP/ET等另行获取。

AlphaEarth原数据为CC BY 4.0。派生成果保留：The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind.

## 其他输入

完整方案§操作手册列NPP/ET、ERA5-Land、地形/标签、水文、能源、空气、文化和生产投入的入口、字段和归档。公开产品可访问与已下载/已验收分别登记。GEE、CDS等登录由数据管理员在本机配置。部门数据申请统一为110108、2024、原始粒度和单位，附许可用途；未收到的输入保持pending。模型采用估计值时记录方法卡、参数出处、时间/地区差异、不确定性和独立审核。
