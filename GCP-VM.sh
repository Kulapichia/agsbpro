#!/bin/bash


# ==================== 核心配置选项 ====================

# 虚拟机数量设置 (修改此变量来设置要创建的虚拟机总数)
VM_COUNT=12

# 机器类型选择 (请修改此变量来选择不同的机器类型)
# 
# 选项1: "f1-micro"  - N1 系列
#   - vCPU: 0.2 (可突发到1.0)
#   - 内存: 0.6 GB
#   - 价格: 最便宜
#
# 选项2: "e2-micro"  - E2 系列 (推荐)
#   - vCPU: 0.25-2 (可突发)
#   - 内存: 1 GB
#   - 价格: 稍高但性价比更好
#
# 选项3: "e2-small"  - E2 系列
#   - vCPU: 1
#   - 内存: 2 GB
#
# 选项4: "e2-medium"  - E2 系列
#   - vCPU: 2
#   - 内存: 4 GB
#
# 选项5: "e2-standard-2"  - E2 系列
#   - vCPU: 2
#   - 内存: 8 GB
#
# 选项6: "e2-standard-4"  - E2 系列
#   - vCPU: 4
#   - 内存: 16 GB
#
# 选项7: "n1-standard-1"  - N1 系列
#   - vCPU: 1
#   - 内存: 3.75 GB
#
# 选项8: "n1-standard-2"  - N1 系列
#   - vCPU: 2
#   - 内存: 7.5 GB
#
# 选项9: "c2-standard-2"  - C2 系列 (高性能计算)
#   - vCPU: 2
#   - 内存: 8 GB
#   - 高性能处理器
#
MACHINE_TYPE="f1-micro"

# 硬盘配置
BOOT_DISK_SIZE="10GB"
BOOT_DISK_TYPE="pd-standard"

# 操作系统镜像配置
# 
# Ubuntu 镜像选项:
#   - ubuntu-2004-lts (Ubuntu 20.04 LTS)
#   - ubuntu-2204-lts (Ubuntu 22.04 LTS) - 推荐
#   - ubuntu-2404-lts (Ubuntu 24.04 LTS) - 最新
#
# CentOS/RHEL 镜像选项:
#   - centos-7 (CentOS 7)
#   - rocky-linux-8 (Rocky Linux 8)
#   - rocky-linux-9 (Rocky Linux 9)
#   - rhel-8 (Red Hat Enterprise Linux 8)
#   - rhel-9 (Red Hat Enterprise Linux 9)
#
# Debian 镜像选项:
#   - debian-11 (Debian 11 Bullseye)
#   - debian-12 (Debian 12 Bookworm)
#
#
# 其他镜像选项:
#   - cos-stable (Container-Optimized OS)
#   - fedora-38 (Fedora 38)
#   - opensuse-leap-15 (openSUSE Leap 15)
#
IMAGE_FAMILY="ubuntu-2204-lts"

# 根据镜像家族自动设置项目
case "$IMAGE_FAMILY" in
    "ubuntu-"*|"ubuntu"*)
        IMAGE_PROJECT="ubuntu-os-cloud"
        ;;
    "centos-"*|"centos"*)
        IMAGE_PROJECT="centos-cloud"
        ;;
    "rocky-linux-"*|"rocky"*)
        IMAGE_PROJECT="rocky-linux-cloud"
        ;;
    "rhel-"*|"rhel"*)
        IMAGE_PROJECT="rhel-cloud"
        ;;
    "debian-"*|"debian"*)
        IMAGE_PROJECT="debian-cloud"
        ;;
    "windows-"*|"windows"*)
        IMAGE_PROJECT="windows-cloud"
        ;;
    "cos-"*|"cos"*)
        IMAGE_PROJECT="cos-cloud"
        ;;
    "fedora-"*|"fedora"*)
        IMAGE_PROJECT="fedora-cloud"
        ;;
    "opensuse-"*|"opensuse"*)
        IMAGE_PROJECT="opensuse-cloud"
        ;;
    *)
        IMAGE_PROJECT="ubuntu-os-cloud"  # 默认使用 Ubuntu
        echo "⚠️  未识别的镜像家族 '$IMAGE_FAMILY'，使用默认项目: $IMAGE_PROJECT"
        ;;
esac

# ==================== 验证配置 ====================

# 根据机器类型自动设置系列名称
case "$MACHINE_TYPE" in
    "f1-micro")
        MACHINE_SERIES="N1"
        ;;
    "e2-micro"|"e2-small"|"e2-medium"|"e2-standard-2"|"e2-standard-4")
        MACHINE_SERIES="E2"
        ;;
    "n1-standard-1"|"n1-standard-2"|"n1-standard-4")
        MACHINE_SERIES="N1"
        ;;
    "c2-standard-2"|"c2-standard-4"|"c2-standard-8")
        MACHINE_SERIES="C2"
        ;;
    *)
        echo "❌ 错误：不支持的机器类型 '$MACHINE_TYPE'"
        echo "💡 支持的类型：f1-micro, e2-micro, e2-small, e2-medium, e2-standard-2, e2-standard-4, n1-standard-1, n1-standard-2, c2-standard-2等"
        exit 1
        ;;
esac

# 验证虚拟机数量设置
if ! [[ "$VM_COUNT" =~ ^[0-9]+$ ]] || [ "$VM_COUNT" -le 0 ]; then
    echo "❌ 错误：虚拟机数量必须是正整数，当前值：$VM_COUNT"
    exit 1
fi

# ==================== 区域配置 ====================
# 定义可用的区域 (按优先级排序)
# 基于Google Cloud的可持续性和可用性数据
regions=(
    "europe-west4"          # 荷兰 - 大量可再生能源 (高优先级)
    "europe-west1"          # 比利时 - 可再生能源 (高优先级)
    "europe-north1"         # 芬兰 - 大量水电和风电 (高优先级)
    "southamerica-east1"    # 巴西圣保罗 - 水电 (高优先级)
    "asia-southeast1"       # 新加坡 - 高优先级
    "asia-northeast1"       # 日本东京 - 相对较低碳排放 (中优先级)
    "asia-northeast3"       # 韩国首尔 - 相对较低碳排放 (中优先级)
    "europe-west3"          # 德国法兰克福 - 可再生能源 (中优先级)
    "australia-southeast1"  # 澳大利亚悉尼 - 备用 (低优先级)
    "us-west3"              # 美国西部 (盐湖城) - 备用 (低优先级)
    "us-east4"              # 美国东部北部 (弗吉尼亚北部) - 备用 (低优先级)
    "europe-west2"          # 英国伦敦 - 备用 (低优先级)
    "asia-east1"            # 台湾 - 备用 (低优先级)
    "us-west2"              # 美国西部 (洛杉矶) - 部分可再生能源 (低优先级)
)

# 区域对应的城市名称（用于虚拟机命名）
region_names=(
    "eu-west4"
    "eu-west1"
    "eu-north1"
    "sa-east1"
    "asia-se1"
    "asia-ne1"
    "asia-ne3"
    "eu-west3"
    "au-se1"
    "us-west3"
    "us-east4"
    "eu-west2"
    "asia-east1"
    "us-west2"
)

# ==================== 开始执行 ====================

echo "🔧 准备环境和防火墙规则..."
echo "⚙️  当前配置:"
echo "   - 虚拟机数量: $VM_COUNT 台"
echo "   - 机器类型: $MACHINE_TYPE ($MACHINE_SERIES 系列)"
echo "   - 硬盘大小: $BOOT_DISK_SIZE ($BOOT_DISK_TYPE)"
echo "   - 操作系统: $IMAGE_FAMILY (项目: $IMAGE_PROJECT)"
echo "💡 要更改配置，请编辑脚本顶部的配置变量"
echo ""
echo "🎯 创建策略: 按优先级顺序尝试所有区域，直到创建满 $VM_COUNT 台虚拟机"
echo "============================================"

# 检查认证状态
echo "🔐 检查认证状态..."
current_account=$(gcloud config get-value account 2>/dev/null)

if [ -z "$current_account" ] || [ "$current_account" = "(unset)" ]; then
    echo "❌ 未认证！需要先登录"
    echo "💡 请运行以下命令之一："
    echo "   1. gcloud auth login    (标准登录)"
    echo "   2. gcloud auth application-default login    (应用默认凭据)"
    echo ""
    echo "如果在 Cloud Shell 中，请尝试："
    echo "   gcloud auth list"
    echo "   gcloud config set account YOUR_EMAIL"
    exit 1
else
    echo "✅ 当前账户: $current_account"
fi

# 检查项目配置
echo "🔍 检查项目配置..."
current_project=$(gcloud config get-value project 2>/dev/null)

if [ -z "$current_project" ] || [ "$current_project" = "(unset)" ]; then
    echo "❌ 未设置默认项目！"
    echo "📋 可用项目列表："
    gcloud projects list --format="table(projectId,name)" 2>/dev/null || echo "无法获取项目列表"
    echo ""
    echo "💡 请选择以下方式之一："
    echo "   1. 手动设置: gcloud config set project YOUR_PROJECT_ID"
    echo "   2. 使用第一个可用项目（自动设置）"
    echo ""
    
    # 尝试自动设置第一个项目
    first_project=$(gcloud projects list --format="value(projectId)" --limit=1 2>/dev/null)
    if [ -n "$first_project" ]; then
        echo "🔄 尝试自动设置项目: $first_project"
        if gcloud config set project "$first_project" >/dev/null 2>&1; then
            echo "✅ 项目设置成功: $first_project"
            current_project="$first_project"
        else
            echo "❌ 自动设置失败，请手动设置项目"
            exit 1
        fi
    else
        echo "❌ 无法获取项目信息，请检查权限"
        exit 1
    fi
else
    echo "✅ 当前项目: $current_project"
fi

# 检查并创建防火墙规则来放行所有端口
echo "🔥 检查防火墙规则..."

# 创建允许所有入站流量的防火墙规则
if ! gcloud compute firewall-rules describe allow-all-ports >/dev/null 2>&1; then
    echo "🔥 创建防火墙规则: allow-all-ports (放行所有端口)..."
    if gcloud compute firewall-rules create allow-all-ports \
        --allow tcp:0-65535,udp:0-65535,icmp \
        --source-ranges 0.0.0.0/0 \
        --target-tags allow-all \
        --description "Allow all ports for virtual machines" >/dev/null 2>&1; then
        echo "✅ 防火墙规则创建成功"
    else
        echo "⚠️  防火墙规则创建失败或已存在"
    fi
else
    echo "✅ 防火墙规则已存在"
fi

echo "============================================"
echo ""
echo "🚀 开始创建虚拟机..."
echo "目标: 创建${VM_COUNT}台 $MACHINE_TYPE 虚拟机"
echo "机器类型: $MACHINE_TYPE ($MACHINE_SERIES 系列)"
echo "操作系统: $IMAGE_FAMILY"
echo "🔥 防火墙: 已放行所有端口 (0-65535)"
echo "🌱 优先选择低碳排放区域（使用可再生能源）"
echo "============================================"

# 统计变量
total_vms_created=0
successful_regions=()
failed_regions=()
quota_exceeded_regions=()
attempts_count=0
max_attempts=2  # 最多尝试所有区域2轮

# 创建临时日志文件用于检测命令执行结果
temp_log="/tmp/gcloud_output_$$.log"

# 持续循环尝试所有区域，直到创建满足数量
while [ "$total_vms_created" -lt "$VM_COUNT" ]; do
    ((attempts_count++))
    echo ""
    echo "🔄 第 $attempts_count 轮尝试 (已创建: $total_vms_created/$VM_COUNT)"
    echo "============================================"
    
    # 当前轮是否有任何成功创建
    round_success=false
    
    # 遍历每个区域
    for i in "${!regions[@]}"; do
        region="${regions[$i]}"
        region_name="${region_names[$i]}"
        
        # 如果已经达到目标数量，停止创建
        if [ "$total_vms_created" -ge "$VM_COUNT" ]; then
            echo "🎉 已达到目标数量 $VM_COUNT 台，停止创建！"
            break 2
        fi
        
        # 计算还需要创建的数量
        remaining=$(($VM_COUNT - total_vms_created))
        
        # 每次尝试创建1台虚拟机（更灵活）
        attempt_count=1
        if [ "$remaining" -gt 3 ]; then
            attempt_count=2  # 如果剩余较多，尝试创建2台
        fi
        
        echo "正在 $region ($region_name) 区域尝试创建 $attempt_count 台虚拟机..."
        
        # 清空临时日志文件
        > "$temp_log"
        
        # 执行创建命令，捕获所有输出到日志文件
        set +e  # 临时禁用错误退出
        gcloud compute instances bulk create \
            --name-pattern="${region_name}-vm-#" \
            --region="$region" \
            --count="$attempt_count" \
            --machine-type="$MACHINE_TYPE" \
            --image-family="$IMAGE_FAMILY" \
            --image-project="$IMAGE_PROJECT" \
            --boot-disk-size="$BOOT_DISK_SIZE" \
            --boot-disk-type="$BOOT_DISK_TYPE" \
            --tags=allow-all \
            --metadata="enable-oslogin=FALSE" > "$temp_log" 2>&1
        
        exit_code=$?
        
        # 检查执行结果
        if [ $exit_code -eq 0 ] && ! grep -i "error" "$temp_log" > /dev/null; then
            # 统计实际创建的虚拟机数量
            created_count=$(grep -c "Created \[" "$temp_log" 2>/dev/null)
            if ! [[ "$created_count" =~ ^[0-9]+$ ]] || [ "$created_count" -eq 0 ]; then
                created_count="$attempt_count"  # 假设全部成功
            fi
            
            echo "✅ $region ($region_name) 区域创建成功 - $created_count 台虚拟机"
            ((total_vms_created+=created_count))
            successful_regions+=("$region_name($region): $created_count 台")
            round_success=true
        else
            # 检查错误类型
            if grep -i "quota.*exceeded\|quota.*limit" "$temp_log" > /dev/null; then
                echo "⚠️  $region ($region_name) 区域配额不足，跳过"
                quota_exceeded_regions+=("$region_name($region)")
            elif grep -i "sufficient capacity\|no available capacity\|capacity.*exhausted" "$temp_log" > /dev/null; then
                echo "⚠️  $region ($region_name) 区域容量不足，跳过"  
            elif grep -i "does not have enough resources\|zone.*does not have enough resources" "$temp_log" > /dev/null; then
                echo "⚠️  $region ($region_name) 区域资源不足，跳过"
            else
                # 检查是否有部分创建成功
                created_count=$(grep -c "Created \[" "$temp_log" 2>/dev/null)
                if ! [[ "$created_count" =~ ^[0-9]+$ ]]; then
                    created_count=0
                fi
                
                if [ "$created_count" -gt 0 ]; then
                    echo "⚠️  $region ($region_name) 区域部分成功 - 创建了 $created_count/$attempt_count 台虚拟机"
                    ((total_vms_created+=created_count))
                    successful_regions+=("$region_name($region): $created_count 台（部分成功）")
                    round_success=true
                else
                    echo "❌ $region ($region_name) 区域创建失败"
                    if [ "$attempts_count" -eq 1 ]; then
                        echo "📄 错误详情:"
                        cat "$temp_log" | head -3
                    fi
                    failed_regions+=("$region_name($region)")
                fi
            fi
        fi
        
        echo "📊 当前进度: 已创建 $total_vms_created/$VM_COUNT 台虚拟机"
        echo "--------------------------------------------"
        
        # 添加短暂延迟避免API限制
        sleep 1
        
        # 如果已经创建了足够的虚拟机，则停止
        if [ "$total_vms_created" -ge "$VM_COUNT" ]; then
            echo "🎉 已达到目标数量，停止创建！"
            break
        fi
    done
    
    # 检查是否需要继续下一轮尝试
    if [ "$total_vms_created" -ge "$VM_COUNT" ]; then
        break
    elif [ "$attempts_count" -ge "$max_attempts" ]; then
        echo ""
        echo "⚠️  已尝试 $max_attempts 轮，无法创建更多虚拟机"
        break
    elif [ "$round_success" = false ]; then
        echo ""
        echo "⚠️  本轮没有成功创建任何虚拟机，可能所有区域都无可用资源"
        break
    else
        echo ""
        echo "🔄 本轮创建了一些虚拟机，继续下一轮尝试..."
        sleep 3  # 稍微长一点的延迟
    fi
done

# 清理临时日志文件
rm -f "$temp_log"

echo ""
echo "🎊 虚拟机创建任务完成！"
echo ""
echo "📊 最终统计："
echo "🖥️  成功创建: $total_vms_created 台虚拟机"
echo "🎯 目标数量: $VM_COUNT 台 $MACHINE_TYPE 虚拟机"
echo "🔄 总尝试轮数: $attempts_count 轮"
echo ""

if [ ${#successful_regions[@]} -gt 0 ]; then
    echo "✅ 成功创建虚拟机的区域："
    for region in "${successful_regions[@]}"; do
        echo "   - $region"
    done
    echo ""
fi

if [ ${#quota_exceeded_regions[@]} -gt 0 ]; then
    echo "⚠️  配额不足的区域："
    for region in "${quota_exceeded_regions[@]}"; do
        echo "   - $region"
    done
    echo ""
fi

if [ "$total_vms_created" -ge "$VM_COUNT" ]; then
    echo "🎉 任务完成！成功创建 $total_vms_created 台虚拟机"
    echo "✨ 已达到目标数量 $VM_COUNT 台！"
else
    remaining=$(($VM_COUNT - total_vms_created))
    echo "⚠️  未完全达成目标，还需要 $remaining 台虚拟机"
    echo ""
    echo "💡 可能的原因："
    echo "   1. 大部分区域配额不足或容量不足"
    echo "   2. 机器类型 $MACHINE_TYPE 在某些区域不可用"
    echo "   3. 免费试用账户限制（如使用Windows镜像）"
    echo ""
    echo "🔧 建议操作："
    echo "   1. 申请配额提升：https://console.cloud.google.com/iam-admin/quotas"
    echo "   2. 尝试更小的机器类型（如e2-micro, e2-small）"
    echo "   3. 检查是否需要启用付费账户"
    echo "   4. 稍后重新运行脚本"
fi

echo ""
echo "📋 使用的配置："
echo "   - 机器类型: $MACHINE_TYPE ($MACHINE_SERIES 系列)"
echo "   - 操作系统: $IMAGE_FAMILY (项目: $IMAGE_PROJECT)"
echo "   - 硬盘大小: $BOOT_DISK_SIZE"
echo "   - 硬盘类型: $BOOT_DISK_TYPE"
echo "   - 防火墙: 放行所有端口 (TCP/UDP 0-65535, ICMP)"
echo "   - 网络标签: allow-all"
echo ""
echo "🔐 连接说明："
echo "   - 使用 SSH 连接: gcloud compute ssh <虚拟机名称> --zone=<区域>"
echo "   - 或使用: ssh -i ~/.ssh/google_compute_engine <用户名>@<虚拟机外部IP>"
echo "   - 查看虚拟机列表: gcloud compute instances list"
echo "   - 所有端口已放行，可直接访问服务"
echo ""
echo "🌱 环保说明："
echo "   - 优先选择使用可再生能源的区域"
echo "   - 欧洲区域使用大量风电和水电"
echo "   - 巴西使用水电，碳排放极低"
