// 当前文件依赖的头文件
#include "stm32f10x.h"   // 包含stm32f10x系列单片机头文件

int main(void)	// 主函数 C语言中有且仅有一个main函数，main函数是程序的入口
{
	// 使用功能的初始化
	
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;
	
	// 2.打开外设的时钟   PA8--GPIOA
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
	
	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_8;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;	// 引脚模式   推挽输出
	
	// 4.初始化GPIO
	GPIO_Init(GPIOA, &GPIO_InitStructure);

	// 功能测试
	while(1)	// 让程序永久循环，不退出、不跑飞、不死机
	{
		GPIO_ResetBits(GPIOA, GPIO_Pin_8);	// 设置低电平，灯亮
//		GPIO_SetBits(GPIOA, GPIO_Pin_8);	// 设置高电平，灯灭
	}
}
