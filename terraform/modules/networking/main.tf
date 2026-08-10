# =============================================================================
# VPC
# =============================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

# =============================================================================
# SUBNETS — for_each over AZs for consistent naming
# =============================================================================

resource "aws_subnet" "public" {
  for_each = { for idx, az in var.azs : az => idx }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, each.value + 1)
  availability_zone       = each.key
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-pub-${each.key}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  for_each = { for idx, az in var.azs : az => idx }

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value + 10)
  availability_zone = each.key

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-priv-${each.key}"
    Tier = "private"
  })
}

# =============================================================================
# INTERNET GATEWAY
# =============================================================================

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

# =============================================================================
# NAT — CONDITIONAL: instance (fck-nat, ~$3/mo) or gateway (~$32/mo)
# =============================================================================
# Demonstrates: count-based conditional resource creation.
# Only ONE of these blocks creates resources, controlled by var.nat_type.

# --- Option A: fck-nat instance ---

data "aws_ami" "fck_nat" {
  count       = var.nat_type == "instance" ? 1 : 0
  most_recent = true
  owners      = ["568608671756"]

  filter {
    name   = "name"
    values = ["fck-nat-al2023-*-arm64-*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

resource "aws_security_group" "nat" {
  count       = var.nat_type == "instance" ? 1 : 0
  name_prefix = "${var.name_prefix}-nat-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [for s in aws_subnet.private : s.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-sg" })
}

resource "aws_instance" "nat" {
  count                  = var.nat_type == "instance" ? 1 : 0
  ami                    = data.aws_ami.fck_nat[0].id
  instance_type          = "t4g.nano"
  subnet_id              = values(aws_subnet.public)[0].id
  vpc_security_group_ids = [aws_security_group.nat[0].id]
  source_dest_check      = false

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })
}

# --- Option B: Managed NAT Gateway ---

resource "aws_eip" "nat" {
  count  = var.nat_type == "gateway" ? 1 : 0
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-nat-eip" })
}

resource "aws_nat_gateway" "nat" {
  count         = var.nat_type == "gateway" ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = values(aws_subnet.public)[0].id
  depends_on    = [aws_internet_gateway.igw]
  tags          = merge(var.tags, { Name = "${var.name_prefix}-nat" })
}

# =============================================================================
# ROUTE TABLES
# =============================================================================

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-pub-rt" })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    # Conditional: point to NAT instance ENI or NAT gateway ID
    network_interface_id = var.nat_type == "instance" ? aws_instance.nat[0].primary_network_interface_id : null
    nat_gateway_id       = var.nat_type == "gateway" ? aws_nat_gateway.nat[0].id : null
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-priv-rt" })
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}
