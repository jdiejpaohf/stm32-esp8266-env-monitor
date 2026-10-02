// 当前文件依赖的头文件
#include "stm32f10x.h"   // 包含stm32f10x系列单片机头文件
#include "led.h"

int main(void)	// 主函数 C语言中有且仅有一个main函数，main函数是程序的入口
{
	// 初始化
	led_init();	// 初始化led

	// 功能测试
	while(1)	// 让程序永久循环，不退出、不跑飞、不死机
	{
		GPIO_ResetBits(GPIOA, GPIO_Pin_8);	// 设置低电平，灯亮
//		GPIO_SetBits(GPIOA, GPIO_Pin_8);	// 设置高电平，灯灭
	}
}
