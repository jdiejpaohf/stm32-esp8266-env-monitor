#include "fan.h"

void fan_init(void)
{
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;
	
	// 2.打开外设的时钟   PC11、PC12--GPIOC
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
	
	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_11 | GPIO_Pin_12;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;	// 引脚模式   推挽输出
	
	// 4.初始化GPIO
	GPIO_Init(GPIOC, &GPIO_InitStructure);
}

/* 
真值表
INA   INB
 0     0   停止   tz
 0     1   反转   fz
 1     0   正转   zz

PC11--INA
PC12--INB

不建议同时给两个引脚高电平，部分模块会进入制动状态，容易发热
*/

void fan_zz(void)	// 风扇正转
{
	PCout(11) = 1;
	PCout(12) = 0;
}

void fan_fz(void)	// 风扇反转
{
	PCout(11) = 0;
	PCout(12) = 1;
}

void fan_tz(void)	// 风扇停止
{
	PCout(11) = 0;
	PCout(12) = 0;
}
