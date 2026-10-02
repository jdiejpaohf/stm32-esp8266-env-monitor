#include "usart.h"

/*
    函数一：int fputc(int ch, FILE *f)
    printf函数中调用了 fputc 这个函数，将格式化后的数据，按照字符打印在标准输出中
    我们当前将 fputc 这个函数，改造成使用串口发送数据
    改造之后，我们就可能使用printf将数据打印到电脑端的串口调试助手中
    这块需要特别注意的是，函数的首部我们不可以进行任何更改，
		否则printf中就不能正常按照我们要求进行调试操作
    一定要将”选项“中的“Use MicroLIB”勾选上
	（选择魔术棒，点击“Target”，在“Target”页签下勾选“Use MicroLIB”）
	原理可参考Cortex M3与M4权威指南
*/
int fputc(int ch, FILE *f)
{
    // 1.将字符发送到USART1的数据寄存器
    // 函数要求传入uint8_t类型，所以对ch进行强制类型转换
    USART_SendData(USART1, (uint8_t)ch);
    
    // 2.等待数据发送完成
    // 检查USART1的“发送完成”标志位（USART_FLAG_TC）
    // 当TC位为RESET（0）时，表示发送还未完成，继续循环等待
    // 当TC位为SET（1）时，表示数据已从移位寄存器完全发送出去，跳出循环
    while(USART_GetFlagStatus(USART1, USART_FLAG_TC) == RESET);
    
    // 3.按照fputc函数的标准要求，返回发送的字符
    return ch;
}


/*
串口通信实现过程:
1、查看原理图 -- USART1_TX--PA9、USART1_RX--PA10
2、添加USART标准外围设备驱动(底层函数)
3、定义GPIO、USART、NVIC(中断控制器)的初始化结构体	
4、打开usart1外设时钟 + GPIOA外设时钟 -- USART1_TX--PA9、USART1_RX--PA10
5、配置GPIO引脚 -- PA9、PA10
      PA9(TX)发送引脚 -- 复用推挽输出
      PA10(RX)接收引脚 -- 输入模式（浮空输入）
6、配置USART1的核心参数
7、配置NVIC全局中断(中断通道+优先级)
8、使能USART1的接收中断，并指定USART1的中断源，当接收到数据时，硬件会自动产生中断请求 -- USART_ITConfig()
9、打开串口 -- USART_Cmd（）函数
10、清除接收中断标志位，防止一启动就进入中断 -- USART_ClearFlag（）
        使能接收中断后，先初始化（清空）接收中断状态标志位
11、编写中断服务函数，当USART1产生中断时，系统会自动调用此函数
 	USART1_IRQHandler()
	USART_GetITStatus（）判断中断是否发生
	USART_ClearITPendingBit（）清除中断标志位
	USART_ReceiveData（）接收数据
	USART_SendData()  发送数据   
	USART_GetFlagStatus（）获取 USART 通信外设的某个状态标志位   

main函数中：
12、调用"初始化代码"函数
*/


// 串口1的初始化
void usart1_init(uint32_t  baud)
{
	// 1.定义GPIO、USART、NVIC(中断控制器)的初始化结构体	
	GPIO_InitTypeDef     GPIO_InitStructure;
	USART_InitTypeDef    USART_InitStructure;
	NVIC_InitTypeDef     NVIC_InitStruct;

	// 2.打开usart1外设时钟 + GPIOA外设时钟 -- USART1_TX--PA9、USART1_RX--PA10
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_USART1, ENABLE);
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);

	// 3.配置GPIO引脚 -- PA9、PA10
	// PA9(TX)发送引脚 -- 复用推挽输出
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_9;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF_PP;		// 复用推挽输出
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &GPIO_InitStructure);

    // 4.PA10(RX)接收引脚 -- 输入模式（浮空输入）
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_10;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING;	// 浮空输入
    GPIO_Init(GPIOA, &GPIO_InitStructure);

	// 5.配置USART1的核心参数
	USART_InitStructure.USART_BaudRate = baud;						// 波特率  115200bps
	USART_InitStructure.USART_WordLength = USART_WordLength_8b;		// 数据位  8bit
	USART_InitStructure.USART_StopBits = USART_StopBits_1;			// 停止位  1bit
	USART_InitStructure.USART_Parity = USART_Parity_No;				// 校验位  无
	USART_InitStructure.USART_HardwareFlowControl = USART_HardwareFlowControl_None; // 无硬件流控制
	USART_InitStructure.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;	// 收发模式
	USART_Init(USART1, &USART_InitStructure);

	// 6.配置NVIC全局中断(中断通道+优先级)
	NVIC_InitStruct.NVIC_IRQChannel = USART1_IRQn;	// 配置中断通道
	NVIC_InitStruct.NVIC_IRQChannelPreemptionPriority = 0x0F;	// 抢占优先级
	NVIC_InitStruct.NVIC_IRQChannelSubPriority = 0x0F;	// 响应优先级
	NVIC_InitStruct.NVIC_IRQChannelCmd = ENABLE;	// 使能中断通道
	NVIC_Init(&NVIC_InitStruct);
	
	// 7.使能USART1的接收中断，并指定USART1的中断源，当接收到数据时，硬件会自动产生中断请求
	USART_ITConfig(USART1,USART_IT_RXNE,ENABLE);
	
	// 8.打开串口1
	USART_Cmd(USART1,ENABLE);
	
	// 9.清除接收中断标志位，防止一启动就进入中断
    //   使能接收中断后，先初始化（清空）接收中断状态标志位
    USART_ClearFlag(USART1, USART_FLAG_RXNE);
}
	

// 串口2的初始化
void usart2_init(uint32_t  baud)
{
	// 1.定义GPIO、USART、NVIC(中断控制器)的初始化结构体	
	GPIO_InitTypeDef     GPIO_InitStructure;
	USART_InitTypeDef    USART_InitStructure;
	NVIC_InitTypeDef     NVIC_InitStruct;

	// 2.打开usart2外设时钟 + GPIOA外设时钟 -- USART2_TX=PA2、USART2_RX=PA3
	RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART2, ENABLE);
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);

	// 3.配置GPIO引脚 -- PA2、PA3
	// PA2(TX)发送引脚   复用推挽输出
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_2;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF_PP;		// 复用推挽输出
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &GPIO_InitStructure);

    // 4.PA3(RX)接收引脚 -- 输入模式（浮空输入）
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_3;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING;	// 浮空输入
    GPIO_Init(GPIOA, &GPIO_InitStructure);


	// 5.配置USART2的核心参数
	USART_InitStructure.USART_BaudRate = baud;						// 波特率  115200bps
	USART_InitStructure.USART_WordLength = USART_WordLength_8b;		// 数据位  8bit
	USART_InitStructure.USART_StopBits = USART_StopBits_1;			// 停止位  1bit
	USART_InitStructure.USART_Parity = USART_Parity_No;				// 校验位  无
	USART_InitStructure.USART_HardwareFlowControl = USART_HardwareFlowControl_None; // 无硬件流控制
	USART_InitStructure.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;	// 收发模式
	USART_Init(USART2, &USART_InitStructure);

	// 6.配置NVIC全局中断(中断通道+优先级)
	NVIC_InitStruct.NVIC_IRQChannel = USART2_IRQn;	// 配置中断通道
	NVIC_InitStruct.NVIC_IRQChannelPreemptionPriority = 0x0F;	// 抢占优先级
	NVIC_InitStruct.NVIC_IRQChannelSubPriority = 0x01;	// 响应优先级
	NVIC_InitStruct.NVIC_IRQChannelCmd = ENABLE;	// 使能中断通道
	NVIC_Init(&NVIC_InitStruct);
	
	// 7.使能USART1的接收中断，并指定USART2的中断源，当接收到数据时，硬件会自动产生中断请求
	USART_ITConfig(USART2,USART_IT_RXNE,ENABLE);
	
	// 8.打开串口
	USART_Cmd(USART2,ENABLE);
	
	// 9.清除接收中断标志位，防止一启动就进入中断
    //   使能接收中断后，先初始化（清空）接收中断状态标志位
    USART_ClearFlag(USART2, USART_FLAG_RXNE);
}


// 10.中断服务函数，当USART1产生中断时，系统会自动调用此函数
void USART1_IRQHandler(void)
{
	uint16_t recv_data = 0;
	
	// 检测中断是否由“接收数据寄存器非空”事件触发
	if( USART_GetITStatus(USART1,USART_IT_RXNE) != RESET )
	{
		// 先读取数据寄存器，这会硬件上自动清除RXNE标志
		recv_data = USART_ReceiveData(USART1);	// 把接收到的数据保存到变量中
		
		// 再清除中断挂起位（实际上在读取数据后，硬件已清除，但调用此函数作为保险）
		USART_ClearITPendingBit(USART1,USART_IT_RXNE);
		
		USART_SendData(USART1,recv_data);	// 把收到的数据发送
		while( USART_GetFlagStatus(USART1,USART_FLAG_TXE) == RESET ); 	// 等待数据发送完成	
	}
}

// 11.中断服务函数，当USART2产生中断时，系统会自动调用此函数
void USART2_IRQHandler(void)
{
	uint16_t recv_data = 0;
	
	// 检测中断是否由“接收数据寄存器非空”事件触发
	if( USART_GetITStatus(USART2,USART_IT_RXNE) != RESET )
	{
		// 先读取数据寄存器，这会硬件上自动清除RXNE标志
		recv_data = USART_ReceiveData(USART2);	// 把接收到的数据保存到变量中
		
		// 再清除中断挂起位（实际上在读取数据后，硬件已清除，但调用此函数作为保险）
		USART_ClearITPendingBit(USART2,USART_IT_RXNE);	// 清除中断标志位

		USART_SendData(USART1,recv_data);	// 把收到的数据发送
		while( USART_GetFlagStatus(USART1,USART_FLAG_TXE) == RESET ); 	// 等待数据发送完成	
	}
}
