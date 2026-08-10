output "endpoint" {
  value = split(":", aws_db_instance.main.endpoint)[0]
}

output "db_name" {
  value = aws_db_instance.main.db_name
}

output "port" {
  value = aws_db_instance.main.port
}
