// 当前文件依赖的头文件
#include "stm32f10x.h"	// 导入stm32f10x系列单片机头文件
#include "led.h"
#include "buz.h"
#include "key.h"
#include "sys.h"
#include "fan.h"
#include "shock.h"
#include "delay.h"
#include "exti.h"
#include "time.h"
#include "pwm.h"


int main(void) // C语言中有且仅有一个main函数，main函数是程序的入口
{
//	// 设置优先级分组
//	NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);
		
	
	// 主函数依赖的变量
	uint16_t i = 0;
	
	
	// 使用功能的初始化
//	led_init();	// 初始化led灯
//	buz_init();	// 初始化蜂鸣器
//	key_init();	// 初始化按键
//	fan_init();	// 初始化风扇
//  shock_init();	// 初始化震动传感器
	delay_init(72);	// 初始化延迟函数
//	key_exti_init();	// 初始化中断
//	time1_init(5000, 7200);	// 初始化定时器1
	LEDPWM_TIM1CH1_Init(100, 7200);	// LEDPWM初始化
	
	// 功能测试
	while(1)	// 让程序永久循化，不退出、不跑飞、不死机
	{
		// 亮度固定
		TIM_SetCompare1(TIM1, 50);	// 占空比越大，灯越暗 1~100
		delay_ms(1000);
		
		// 亮度渐变
		// 灯渐灭
		for( i=0;i<100;i+=5 )
		{
			TIM_SetCompare1(TIM1, i);	// 占空比越大，灯越暗 1~100
			delay_ms(500);
		}
		
		// 灯渐亮
		for( i=100;i>0;i-=5 )
		{
			TIM_SetCompare1(TIM1, i);	// 占空比越小，灯越亮 1~100
			delay_ms(500);
		}
	}
}
