variable "name_prefix" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "azs" {
  type = list(string)
}

variable "nat_type" {
  description = "NAT implementation: 'instance' or 'gateway'"
  type        = string
}

variable "tags" {
  type = map(string)
}
